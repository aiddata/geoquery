from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import connection

from analytics.tasks.processing import run_extract_task

logger = getLogger(__name__)


class Command(BaseCommand):
    help = "Trigger dispatching of pending processing tasks (e.g. extract tasks) to Celery workers"

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
            default=1000,
            help="Maximum number of tasks to dispatch",
        )

    def handle(self, *args, **options):
        _run_processing_tasks(limit=options["limit"], dry_run=options["dry_run"])


def _run_processing_tasks(limit=1000, dry_run=False):
    """Dispatch pending extract tasks (status=0) to Celery workers."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id FROM extract_tasks
            WHERE status = 0
            ORDER BY priority DESC, submit_time ASC
            LIMIT %s
            """,
            [limit],
        )
        task_ids = [row[0] for row in cursor.fetchall()]

    if not task_ids:
        logger.info("No pending extract tasks to dispatch")
        return {"dispatched": 0}

    if not dry_run:
        for tid in task_ids:
            run_extract_task.delay(tid)
        logger.info("Dispatched %d extract tasks", len(task_ids))
    else:
        logger.info("Would dispatch %d extract tasks (dry-run)", len(task_ids))

    return {"dispatched": len(task_ids), "dry_run": dry_run}