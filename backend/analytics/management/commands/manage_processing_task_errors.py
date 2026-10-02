import time
from datetime import datetime, timedelta
from typing import Union

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


from loguru import logger


"""
Module for handling edge-cases and errors.
"""


class Command(BaseCommand):
    help = "Generate missing coverage records and kick off spatial coverage testing"

    def add_arguments(self, parser):
        # boolean
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Run the command without making any changes to the database, just log the number of errored tasks that would be updated.",
        )
        parser.add_argument(
            "--error-values",
            type=str,
            default=-1,
            help="Error status values to update.",
        )
        parser.add_argument(
            "--max-attempts",
            type=int,
            default=None,
            help=(
                "Give up on a task once it has been retried this many times. "
                "Defaults to settings.MAX_EXTRACT_TASK_ATTEMPTS."
            ),
        )

    def handle(self, *args, **options):
        """
        This command identifies extract tasks that are in an error state (status values specified by --error-values) and resets them to pending (status=0) so they can be reprocessed and increments the attempt count for each task. This allows tasks that may have failed due to transient issues to be retried.
        """
        _manage_processing_task_errors(
            error_values=options["error_values"],
            dry_run=options["dry_run"],
            max_attempts=options["max_attempts"],
        )


def _manage_processing_task_errors(
    error_values: Union[int, str],
    dry_run: bool = False,
    max_attempts: Union[int, None] = None,
):
    """Return errored tasks to pending so they are retried, up to a limit.

    The attempts < max_attempts guard is what stops a permanently-failing task
    cycling -1 -> 0 -> -1 forever. `attempts` was incremented here long before
    anything read it; this is the reader. A task that reaches the limit is left
    at status = -1 and _check_request_tasks treats it as finished-but-failed,
    so a request containing one completes without that column instead of
    waiting on it indefinitely.

    Both statements name attempts as well as status so they can use
    extract_tasks_errored_idx (migration 0029), which is keyed on attempts
    precisely because exhausted tasks stay at -1 forever -- without the key
    the sweep would re-read all of them on every run.
    """
    if max_attempts is None:
        max_attempts = settings.MAX_EXTRACT_TASK_ATTEMPTS

    if isinstance(error_values, int):
        error_values = [error_values]
    else:
        error_values = [int(val.strip()) for val in error_values.split(",")]

    with connection.cursor() as cursor:
        for ev in error_values:
            if dry_run:
                cursor.execute(
                    """
                        SELECT COUNT(*) FROM extract_tasks
                        WHERE status = %s AND attempts < %s
                        """,
                    [ev, max_attempts],
                )
                count = cursor.fetchone()[0]
                cursor.execute(
                    """
                        SELECT COUNT(*) FROM extract_tasks
                        WHERE status = %s AND attempts >= %s
                        """,
                    [ev, max_attempts],
                )
                exhausted = cursor.fetchone()[0]
                logger.info(
                    f"Would update {count} tasks with status {ev} (disable --dry-run to actually update them)"
                )
                if exhausted:
                    logger.warning(
                        f"{exhausted} task(s) with status {ev} have reached "
                        f"{max_attempts} attempts and are no longer retried"
                    )

            else:
                cursor.execute(
                    """
                        UPDATE extract_tasks
                        SET status = 0, attempts = attempts + 1, update_time = NOW()
                        WHERE status = %s AND attempts < %s
                        """,
                    [ev, max_attempts],
                )
                updated = cursor.rowcount
                updated = (
                    updated if updated is not None else 0
                )  # rowcount can be None in some cases

                logger.info(
                    f"Updated {updated} tasks with status {ev} to pending and incremented attempts"
                )

    return
