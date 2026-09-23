import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task
def manage_processing_task_errors():
    """Reset errored extract tasks (status=-1) back to pending for retry."""
    from analytics.management.commands.manage_processing_task_errors import (
        _manage_processing_task_errors,
    )

    _manage_processing_task_errors(error_values=-1)


@shared_task
def free_stale_processing_tasks():
    """Reset extract tasks stuck in locked (status=2) back to pending (status=0)."""
    from analytics.management.commands.free_stale_processing_tasks import (
        _free_stale_tasks,
    )

    stale_minutes = getattr(settings, "STALE_TASK_MINUTES", 30)
    freed = _free_stale_tasks(stale_minutes)
    logger.info("Freed %d stale extract tasks", freed)
    return {"freed": freed}


@shared_task
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
def dispatch_processing_tasks():
    """Bootstrap or top up extract task chains to fill idle worker slots.

    Each running extract task self-chains (dispatches the next task on
    completion), so this beat only needs to fill gaps -- idle workers after
    startup, or chains that died due to worker crashes.
    """
    from celery import current_app
    from analytics.management.commands.run_processing_tasks import _run_processing_tasks

    TASK = "analytics.tasks.processing.run_extract_task"
    queue = settings.CELERY_TASK_ROUTES[TASK]["queue"]

    # Only workers consuming the processing queue can run extract tasks, so
    # find those first and scope the remaining broadcasts to them. That keeps
    # the background workers' pool slots out of the count, and lets each call
    # return as soon as those workers reply instead of waiting out the timeout
    # on stale entries in the gossip table.
    inspect = current_app.control.inspect(timeout=5.0)
    active_queues = inspect.active_queues() or {}
    workers = [
        name
        for name, queues in active_queues.items()
        if any(q.get("name") == queue for q in queues)
    ]
    if not workers:
        logger.warning("No workers consuming the %r queue; nothing dispatched", queue)
        return {"dispatched": 0, "total_slots": 0, "in_flight": 0}

    inspect = current_app.control.inspect(destination=workers, timeout=5.0)
    stats = inspect.stats() or {}
    active = inspect.active() or {}
    reserved = inspect.reserved() or {}

    # Filter by name as well as by destination, so a reply from a worker that
    # joined between the two broadcasts can't be counted on one side only.
    total_slots = sum(
        w.get("pool", {}).get("max-concurrency", 0)
        for name, w in stats.items()
        if name in workers
    )
    in_flight = sum(
        1
        for source in (active, reserved)
        for name, tasks in source.items()
        if name in workers
        for t in tasks
        if t["name"] == TASK
    )
    to_dispatch = max(0, total_slots - in_flight)

    logger.info(
        "Extract tasks: %d workers, %d total slots, %d in flight, dispatching %d",
        len(workers), total_slots, in_flight, to_dispatch,
    )
    if to_dispatch == 0:
        return {"dispatched": 0, "total_slots": total_slots, "in_flight": in_flight}

    # to_dispatch counts idle *slots*, i.e. messages to publish, but
    # _run_processing_tasks takes a task limit -- and one message now carries
    # a batch of them. Claiming the whole wave in one call also means one
    # advisory lock acquisition for the entire top-up instead of one per slot.
    from analytics.tasks.processing import _claim_batch_size

    return _run_processing_tasks(limit=to_dispatch * _claim_batch_size())


@shared_task
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
def build_stats_report():
    """Regenerate the statistics snapshot the /stats page reads."""
    from stats.builder import StatsBuilder

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
def build_extract_tasks():
    """Launch parallel global-dataset task generation, plus one pass over the
    (cheap) non-global/coverage-gated branch.

    Fire-and-forget for the parallel workers: this does not wait on them,
    since blocking on child-task results from within the same worker pool
    risks deadlock if all concurrency slots end up waiting rather than
    working. try_acquire_build_run guards against celery-beat's daily
    schedule launching a fresh wave on top of one still working through the
    backlog -- see build_extract_tasks.py for why that matters.
    """
    from analytics.management.commands.build_extract_tasks import (
        _build_non_global_tasks,
        try_acquire_build_run,
    )

    if try_acquire_build_run():
        for _ in range(_n_extract_task_builders()):
            build_extract_tasks_worker.delay()
    else:
        logger.info("build_extract_tasks: a wave is already in progress, not dispatching another")

    return _build_non_global_tasks()


@shared_task
def build_extract_tasks_worker():
    """One parallel worker's share of the global-dataset backlog. Safe to run
    many of these concurrently -- see build_extract_tasks.py."""
    from analytics.management.commands.build_extract_tasks import _build_global_tasks

    return _build_global_tasks()


@shared_task
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
