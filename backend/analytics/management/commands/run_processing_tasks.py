from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import connection

from analytics.tasks.processing import dispatch_pending_tasks

logger = getLogger(__name__)


class Command(BaseCommand):
    help = "Dispatch pending extract tasks (status=0) to the processing workers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Do not actually dispatch tasks, just print how many would be dispatched",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of tasks to dispatch",
        )

    def handle(self, *args, **options):
        _run_processing_tasks(limit=options["limit"], dry_run=options["dry_run"])


def _run_processing_tasks(limit=1000, dry_run=False):
    """Claim up to ``limit`` pending extract tasks and dispatch them to Celery.

    Rows move to queued (status=3) as they are claimed, so calling this again
    before the workers catch up dispatches the *next* batch rather than the
    same one twice.
    """
    if dry_run:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM (SELECT 1 FROM extract_tasks WHERE status = 0 LIMIT %s) AS pending",
                [limit],
            )
            count = cursor.fetchone()[0]
        logger.info("Would dispatch %d extract tasks (dry-run)", count)
        return {"dispatched": count, "dry_run": True}

    task_ids = dispatch_pending_tasks(limit)
    if task_ids:
        logger.info("Dispatched %d extract tasks", len(task_ids))
    else:
        logger.info("No pending extract tasks to dispatch")
    return {"dispatched": len(task_ids), "dry_run": False}
