import logging

from django.core.management.base import BaseCommand
from django.db import connection

logger = logging.getLogger(__name__)

# Locked (2): a worker claimed the row and died before finishing.
# Queued (3): the row was claimed for dispatch but its message never reached a
# worker (broker outage, worker killed mid-publish). Either way the work is
# still owed and nothing else will pick it up until it is pending again.
STALE_STATUSES = (2, 3)


class Command(BaseCommand):
    help = "Reset tasks stuck in 'locked' (status=2) or 'queued' (status=3) back to pending."

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
            help="Number of minutes after which locked or queued tasks are considered stale and reset to pending",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM extract_tasks
                    WHERE status IN %s
                    AND update_time < NOW() - INTERVAL '%s minutes'
                    """,
                    [STALE_STATUSES, options["minutes"]],
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


def _free_stale_tasks(minutes):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE extract_tasks
            SET status = 0, update_time = NOW()
            WHERE status IN %s
            AND update_time < NOW() - INTERVAL '%s minutes'
            """,
            [STALE_STATUSES, minutes],
        )
        freed = cursor.rowcount
        return freed if freed is not None else 0
