import logging

from celery import shared_task

from analytics.query_tags import tagged
from django.conf import settings

from analytics.background_metrics import observe_job

logger = logging.getLogger(__name__)


@shared_task
@tagged("sweep.errors")
def manage_processing_task_errors():
    """Reset errored extract tasks (status=-1) back to pending for retry."""
    from analytics.management.commands.manage_processing_task_errors import (
        _manage_processing_task_errors,
    )

    _manage_processing_task_errors(error_values=-1)


@shared_task
@tagged("sweep.stale")
@observe_job("task_reaper")
def free_stale_processing_tasks():
    """Reset extract tasks stuck in running (status=2) back to pending (status=0)."""
    from analytics.management.commands.free_stale_processing_tasks import (
        _free_stale_tasks,
    )

    stale_minutes = getattr(settings, "STALE_TASK_MINUTES", 30)
    freed = _free_stale_tasks(stale_minutes)
    logger.info("Freed %d stale extract tasks", freed)
    return {"freed": freed}


@shared_task
@tagged("sweep.autovacuum")
@observe_job("autovacuum_reconcile")
def reconcile_partition_autovacuum():
    """Keep each extract_tasks partition on the autovacuum profile its state needs.

    See analytics.partition_vacuum for the two profiles and why one setting
    cannot serve both.
    """
    from analytics.partition_vacuum import reconcile_partition_autovacuum as reconcile

    result = reconcile()
    result.pop("changes")  # each change is logged as it is made
    logger.info("Partition autovacuum: %s", result)
    return result


@shared_task
@tagged("sweep.requests")
@observe_job("request_reaper")
def reset_stale_requests():
    """Recover requests and output that nothing else would pick up again.

    Three strands, each invisible to the completion sweep (which selects
    only status -1 and 0): claims stranded at status=2 by a crashed sweep,
    requests stranded at status=4 because their materialization task never
    ran, and the output paths a hard-killed sweep left in the requests
    directory -- including restoring output that a kill mid-swap left sitting
    in a ".replaced." aside with nothing at the path its download link points
    at. See _clean_orphan_output_dirs for why the two orphan kinds are not
    interchangeable.
    """
    from analytics.management.commands.reset_stale_requests import (
        _clean_orphan_output_dirs,
        _redispatch_unmaterialized_requests,
        _reset_stale_requests,
    )

    stale_minutes = getattr(settings, "STALE_TASK_MINUTES", 30)
    result = _reset_stale_requests(stale_minutes)
    unmaterialized = _redispatch_unmaterialized_requests(stale_minutes)
    orphans = _clean_orphan_output_dirs(str(settings.REQUESTS_DIR), stale_minutes)
    logger.info(
        "Reset %d stale claimed requests; re-dispatched %d unmaterialized; "
        "removed %d abandoned output paths, restored %d displaced outputs",
        result["reset"],
        unmaterialized["redispatched"],
        orphans["removed"],
        orphans["restored"],
    )
    return {
        **result,
        "unmaterialized": unmaterialized["count"],
        "redispatched": unmaterialized["redispatched"],
        **orphans,
    }


@shared_task
@tagged("requests.complete")
@observe_job("request_sweep")
def process_user_requests():
    """Check request queue and advance any requests that are ready."""
    from django.conf import settings

    from analytics.management.commands.manage_user_requests import _manage_user_requests

    _manage_user_requests(
        download_base=getattr(settings, "DOWNLOAD_BASE_URL", "").rstrip("/"),
        frontend_base=getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/"),
        requests_dir=str(settings.REQUESTS_DIR),
        assets_dir=str(settings.ASSETS_DIR),
    )


@shared_task
@tagged("stats")
def build_stats_report():
    """Regenerate the statistics snapshot the /stats page reads."""
    from stats.builder import StatsBuilder

    # Disabling drops the beat entry, but a message queued before the restart
    # could still arrive.
    if not settings.STATS_REPORT_ENABLED:
        logger.info("Stats report build: disabled")
        return {"status": "Disabled"}

    output = getattr(
        settings,
        "STATS_REPORT_PATH",
        str(settings.REQUESTS_DIR / "geoquery_stats.json"),
    )
    status = StatsBuilder(output).build()
    logger.info("Stats report build: %s", status)
    return {"status": status}


def _n_extract_task_builders():
    """How many build workers one wave fans out to.

    Each one holds a pooler connection for the length of its INSERT batch --
    measured in production at 11-20s a transaction, against milliseconds for
    everything processing does. Six of them running concurrently roughly
    halved extract task throughput (~43k/min with the builder idle, ~22k/min
    with it running), and that penalty lands on user-requested tasks too:
    a request's tasks are priority-bumped ahead of the backlog, but they
    still run at whatever rate the fleet is managing. That trade is why this
    is a knob rather than a constant.

    Which side is scarce has since flipped. When this was set to 2, build-out
    was outpacing processing ~3:1 and the right move was to starve the
    builder. After the claim batching work took processing to ~43k/min, a
    12-hour window on 2026-09-23 measured the reverse:

        built      905,709/hr   (~15.1k/min)
        completed  2,276,650/hr (~37.9k/min)

    Processing now clears tasks 2.5x faster than the builder creates them.
    The 191M pending backlog hides that -- it is a buffer draining at
    ~1.37M/hr, so it lasts under six days -- but against the ~1.2B target
    the builder needs ~40 days to finish supplying work that processing
    could consume in ~20. Past the point the buffer empties, the builder
    rate IS the pipeline rate.

    So 4, not 2: enough to close the gap without returning to the six-way
    fan-out that halved throughput. Expect processing to give up some rate
    in exchange; the number worth watching is not either rate alone but
    whether the backlog still drains.
    """
    from django.conf import settings

    return max(1, getattr(settings, "N_EXTRACT_TASK_BUILDERS", 4))



@shared_task
@tagged("builder.launch")
@observe_job("builder_dispatch")
def build_extract_tasks():
    """Launch parallel global-dataset task generation, plus one pass over the
    (cheap) non-global/coverage-gated branch.

    Fire-and-forget for the parallel workers: this does not wait on them,
    since blocking on child-task results from within the same worker pool
    risks deadlock if all concurrency slots end up waiting rather than
    working. try_acquire_build_run guards against celery-beat's configured
    schedule launching a fresh wave on top of one still working through the
    backlog -- see build_extract_tasks.py for why that matters.
    """
    from analytics.management.commands.build_extract_tasks import (
        _build_non_global_tasks,
        try_acquire_build_run,
    )

    worker_count = _n_extract_task_builders()
    run_id = try_acquire_build_run(worker_count)
    if run_id is not None:
        for _ in range(worker_count):
            build_extract_tasks_worker.delay(run_id=str(run_id))
    else:
        logger.info("build_extract_tasks: a wave is already in progress, not dispatching another")

    return _build_non_global_tasks()


@shared_task
@tagged("builder.worker")
@observe_job("builder")
def build_extract_tasks_worker(run_id=None):
    """One parallel worker's share of the global-dataset backlog. Safe to run
    many of these concurrently -- see build_extract_tasks.py."""
    from analytics.management.commands.build_extract_tasks import _build_global_tasks, finish_build_worker

    try:
        return _build_global_tasks(run_id=run_id)
    finally:
        if run_id is not None:
            finish_build_worker(run_id)


@shared_task
@tagged("coverage.sweep")
def sweep_coverage_records():
    """Create any missing coverage records and dispatch checks for unchecked ones."""
    from analytics.tasks.coverage import (
        create_missing_coverage_records,
        run_missing_coverage_checks,
    )

    result = create_missing_coverage_records()
    logger.info("Coverage sweep created %d missing records", result.get("created", 0))
    run_missing_coverage_checks(sync=False)
    return result


@shared_task
def trigger_coverage_and_extract():
    """Create missing coverage records, check all uncovered ones, then build extract tasks.

    Uses a Celery chord so build_extract_tasks only fires after every coverage
    check task has completed.
    """
    from celery import chord, group

    from analytics.models import Coverage
    from analytics.tasks.coverage import create_missing_coverage_records, test_coverage_for_dataset

    result = create_missing_coverage_records()
    logger.info("Created %d missing coverage records", result["created"])

    unchecked_ids = list(
        Coverage.objects.filter(status=-1).values_list("dataset_id", flat=True).distinct()
    )

    if not unchecked_ids:
        logger.info("No unchecked coverage records; running build_extract_tasks directly")
        from analytics.management.commands.build_extract_tasks import _build_extract_tasks

        return _build_extract_tasks()

    chord(
        group(test_coverage_for_dataset.s(did) for did in unchecked_ids),
        build_extract_tasks.si(),
    ).delay()

    logger.info("Dispatched coverage chord for %d datasets → build_extract_tasks", len(unchecked_ids))
    return {"dispatched": len(unchecked_ids)}


@shared_task
def run_user_outreach():
    """Flag users who qualify for outreach (manual mode, default criteria)."""
    from analytics.management.commands.run_user_outreach import _run_user_outreach

    _run_user_outreach(
        n_days=365,
        request_count=3,
        earliest_request=14,
        latest_request=7,
        mode="manual",
    )
