import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task
def free_stale_processing_tasks():
    """Reset extract tasks stuck in locked (status=2) back to pending (status=0)."""
    from analytics.management.commands.free_stale_processing_tasks import _free_stale_tasks
    stale_minutes = getattr(settings, "STALE_TASK_MINUTES", 30)
    freed = _free_stale_tasks(stale_minutes)
    logger.info("Freed %d stale extract tasks", freed)
    return {"freed": freed}