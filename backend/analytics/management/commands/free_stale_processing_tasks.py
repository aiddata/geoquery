import time
import logging
from django.core.management.base import BaseCommand
from django.db import connection


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Reset tasks stuck in 'locked' (status=2) state back to pending."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Do not actually update tasks, just print how many would be freed",
        )
        parser.add_argument(
            "--minutes",
            type=int,
            default=30,
            help="Number of minutes after which 'locked' tasks are considered stale and reset to pending",
        )

    def handle(self, *args, **options):
        """
        Replaces gqcore.utils.db.extract_task_watch.free_dangling_tasks.
        """
        if options["dry_run"]:

            with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM extract_tasks
                        WHERE status = 2
                        AND update_time < NOW() - INTERVAL '%s minutes'
                        """,
                        [options["minutes"]],
                    )
                    freed = cursor.fetchone()[0]

                    self.stdout.write(
                        self.style.WARNING(
                            f"Would free {freed} stale extract tasks (disable --dry-run to actually free them)"
                        )
                    )
        else:
            freed = _free_stale_tasks(options["minutes"])
            self.stdout.write(self.style.SUCCESS(f"Freed {freed} stale extract tasks"))

        return


def _free_stale_tasks(minutes):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE extract_tasks
            SET status = 0, update_time = NOW()
            WHERE status = 2
            AND update_time < NOW() - INTERVAL '%s minutes'
            """,
            [minutes],
        )
        freed = cursor.rowcount
        return freed if freed is not None else 0
