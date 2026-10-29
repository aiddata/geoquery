import logging

from celery import shared_task

from analytics.query_tags import tagged
from django.conf import settings

from analytics.background_metrics import observe_job

logger = logging.getLogger(__name__)


@shared_task
@tagged("sweep.errors")
@observe_job("error_sweep")
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


@shared_task(ignore_result=True)
@tagged("extract.sync")
@observe_job("extract_sync")
def sync_extract_work():
    """Reconcile input changes into pairs, resets and rewinds (analytics.sync).

    Beat runs this every EXTRACT_SYNC_INTERVAL_SECONDS; ingest and model
    signals also wake it after their transactions commit. Either way the
    changes it consumes are already durable in extract_input_state, so a lost
    or duplicated message costs only latency. Each call does a bounded number
    of short transactions (EXTRACT_SYNC_CHUNKS_PER_RUN) and concurrent calls
    skip each other's scopes. Health gauges are refreshed on every run, so they
    keep reporting even when the processing fleet is scaled to zero.
    """
    from analytics.background_metrics import update_extract_health
    from analytics.sync import sync_extract_work as run

    stats = run()
    try:
        update_extract_health()
    except Exception:
        logger.warning("Could not refresh extract health gauges", exc_info=True)
    if stats["chunks"] or stats["errors"]:
        logger.info("Extract sync: %s", stats)
    return stats


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
