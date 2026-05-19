import time

from django.core.management.base import BaseCommand
from django.db import connection

from analytics.tasks.processing import run_extract_task


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
        """
        This is the replacement for the Dask/ProcessPoolExecutor dispatch loop.
        Call it periodically (e.g. via celery-beat) or from a management command.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM extract_tasks
                WHERE status = 0
                ORDER BY priority DESC, submit_time ASC
                LIMIT %s
                """,
                [options["limit"]],
            )
            task_ids = [row[0] for row in cursor.fetchall()]

        if not task_ids:
            self.stdout.write(
                self.style.WARNING(
                    "No pending extract tasks to dispatch"
                )
            )
            return

        if not options["dry_run"]:
            for tid in task_ids:
                run_extract_task.delay(tid)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Dispatched {len(task_ids)} extract tasks"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Would dispatch {len(task_ids)} extract tasks (disable --dry-run to actually dispatch them)"
                )
            )

        return
