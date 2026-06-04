from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import connection

logger = getLogger(__name__)


class Command(BaseCommand):
    help = "Reset requests stuck in error state (status=-2) back to queued (status=-1) for reprocessing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Print how many requests would be reset without making changes.",
        )

    def handle(self, *args, **options):
        result = _reset_errored_requests(dry_run=options["dry_run"])
        if options["dry_run"]:
            self.stdout.write(f"Would reset {result['count']} errored requests (--dry-run).")
        else:
            self.stdout.write(self.style.SUCCESS(f"Reset {result['reset']} errored requests to queued."))


def _reset_errored_requests(dry_run: bool = False) -> dict:
    with connection.cursor() as cursor:
        if dry_run:
            cursor.execute("SELECT COUNT(*) FROM requests WHERE status = -2")
            count = cursor.fetchone()[0]
            return {"count": count}
        cursor.execute(
            """
            UPDATE requests
            SET status = -1
            WHERE status = -2
            """
        )
        reset = cursor.rowcount or 0
    logger.info("Reset %d errored requests to queued", reset)
    return {"reset": reset}