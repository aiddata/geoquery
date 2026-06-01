import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task
def manage_processing_task_errors():
    """Reset errored extract tasks (status=-2) back to pending for retry."""
    from analytics.management.commands.manage_processing_task_errors import _manage_processing_task_errors
    _manage_processing_task_errors(error_values=-2)


@shared_task
def free_stale_processing_tasks():
    """Reset extract tasks stuck in locked (status=2) back to pending (status=0)."""
    from analytics.management.commands.free_stale_processing_tasks import _free_stale_tasks
    stale_minutes = getattr(settings, "STALE_TASK_MINUTES", 30)
    freed = _free_stale_tasks(stale_minutes)
    logger.info("Freed %d stale extract tasks", freed)
    return {"freed": freed}


@shared_task
def build_stats_report():
    """Regenerate the HTML statistics report."""
    from stats.builder import StatsBuilder
    output = getattr(settings, "STATS_REPORT_PATH", str(settings.RESULTS_DIR / "geoquery_stats.html"))
    status = StatsBuilder(output).build()
    logger.info("Stats report build: %s", status)
    return {"status": status}


@shared_task
def sweep_coverage_records():
    """Create any missing coverage records and dispatch checks for unchecked ones."""
    from analytics.tasks.coverage import create_missing_coverage_records, run_missing_coverage_checks
    result = create_missing_coverage_records()
    logger.info("Coverage sweep created %d missing records", result.get("created", 0))
    run_missing_coverage_checks(sync=False)
    return result


@shared_task
def run_user_outreach():
    """Flag users who qualify for outreach (manual mode, default criteria)."""
    from django.core.management import call_command
    call_command("run_user_outreach", mode="manual")