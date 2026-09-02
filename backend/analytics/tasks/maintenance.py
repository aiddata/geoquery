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
def dispatch_processing_tasks():
    """Bootstrap or top up extract task chains to fill idle worker slots.

    Each running extract task self-chains (dispatches the next task on
    completion), so this beat only needs to fill gaps — idle workers after
    startup, or chains that died due to worker crashes.
    """
    from celery import current_app
    from analytics.management.commands.run_processing_tasks import _run_processing_tasks

    TASK = "analytics.tasks.processing.run_extract_task"
    inspect = current_app.control.inspect(timeout=5.0)
    stats = inspect.stats() or {}
    active = inspect.active() or {}
    reserved = inspect.reserved() or {}

    total_slots = sum(w.get("pool", {}).get("max-concurrency", 0) for w in stats.values())
    in_flight = sum(
        1 for tasks in list(active.values()) + list(reserved.values())
        for t in tasks if t["name"] == TASK
    )
    to_dispatch = max(0, total_slots - in_flight)

    logger.info(
        "Extract tasks: %d total slots, %d in flight, dispatching %d",
        total_slots, in_flight, to_dispatch,
    )
    if to_dispatch == 0:
        return {"dispatched": 0, "total_slots": total_slots, "in_flight": in_flight}

    return _run_processing_tasks(limit=to_dispatch)


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
    """Regenerate the HTML statistics report."""
    from stats.builder import StatsBuilder

    output = getattr(
        settings,
        "STATS_REPORT_PATH",
        str(settings.REQUESTS_DIR / "geoquery_stats.html"),
    )
    status = StatsBuilder(output).build()
    logger.info("Stats report build: %s", status)
    return {"status": status}


@shared_task
def build_extract_tasks():
    """Create ExtractTask rows for any covered (status=1) dataset/feature pairs that don't have one yet."""
    from analytics.management.commands.build_extract_tasks import _build_extract_tasks

    return _build_extract_tasks()


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
