import re
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Union

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


from loguru import logger


"""
Module for handling edge-cases and errors.
"""


# extract_tasks.error holds repr(exc)[:100] (see processing._run_extract_task),
# so it starts with the exception's class name: RasterioIOError('/data/...').
# Only that leading name becomes a metric label -- the rest is a message
# carrying file paths and coordinates, which would make the label unbounded.
# The full text still goes to the log.
_EXCEPTION_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")

# A successful retry overwrites error with NULL, so this sweep is the last
# chance to read why a task failed. Logging every one of them is right at the
# normal handful per day and wrong during a mass failure, where it would bury
# everything else -- so log a sample and let the metric carry the full count.
_LOG_SAMPLE = 20


def _exception_class(error):
    """Return the exception class name from a stored error, for a label.

    Never raises and never returns None: a label that cannot be derived still
    has to be countable, or the failure disappears from the metric entirely.
    """
    error = (error or "").strip()
    if not error:
        return "unrecorded"
    match = _EXCEPTION_CLASS.match(error)
    return match.group(0)[:60] if match else "unparsed"


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

    This is also where a failure is recorded, because it is the only path out
    of the error status: every failed task passes through here exactly once,
    and the retry then overwrites `error` with NULL, so afterwards nothing can
    still see why the task failed. The exception class goes to a counter and
    the full text to the log. Deliberately not instrumented in the worker
    instead -- that path runs thousands of tasks a second, this one runs six
    times an hour over a handful of rows.
    """
    from analytics.background_metrics import (
        record_task_failures,
        record_work,
        set_tasks_exhausted,
    )

    if max_attempts is None:
        max_attempts = settings.MAX_EXTRACT_TASK_ATTEMPTS

    if isinstance(error_values, int):
        error_values = [error_values]
    else:
        error_values = [int(val.strip()) for val in error_values.split(",")]

    exhausted_total = 0
    with connection.cursor() as cursor:
        for ev in error_values:
            # Counted on both paths, not just --dry-run. An exhausted task is
            # never retried again and _check_request_tasks lets a request
            # containing one complete without that column, so this number is
            # the only way anyone learns it happened.
            cursor.execute(
                """
                    SELECT COUNT(*) FROM extract_tasks
                    WHERE status = %s AND attempts >= %s
                    """,
                [ev, max_attempts],
            )
            exhausted = cursor.fetchone()[0]
            exhausted_total += exhausted
            if exhausted:
                logger.warning(
                    f"{exhausted} task(s) with status {ev} have reached "
                    f"{max_attempts} attempts and are no longer retried"
                )

            if dry_run:
                cursor.execute(
                    """
                        SELECT COUNT(*) FROM extract_tasks
                        WHERE status = %s AND attempts < %s
                        """,
                    [ev, max_attempts],
                )
                count = cursor.fetchone()[0]
                logger.info(
                    f"Would update {count} tasks with status {ev} (disable --dry-run to actually update them)"
                )

            else:
                cursor.execute(
                    """
                        UPDATE extract_tasks
                        SET status = 0, attempts = attempts + 1, update_time = NOW()
                        WHERE status = %s AND attempts < %s
                        RETURNING dataset_id, id, attempts, error
                        """,
                    [ev, max_attempts],
                )
                retried = cursor.fetchall()
                updated = len(retried)

                by_exception = Counter()
                for shown, row in enumerate(retried):
                    dataset_id, task_id, attempts, error = row
                    by_exception[_exception_class(error)] += 1
                    if shown < _LOG_SAMPLE:
                        logger.warning(
                            f"Retrying extract task {task_id} (dataset {dataset_id}, "
                            f"attempt {attempts} of {max_attempts}): "
                            f"{error or 'no error recorded'}"
                        )
                if updated > _LOG_SAMPLE:
                    logger.warning(
                        f"{updated - _LOG_SAMPLE} further failure(s) not logged "
                        f"individually; geoquery_extract_task_failures has the full "
                        f"count by exception"
                    )

                record_task_failures(by_exception)
                record_work("tasks_retried", updated)
                logger.info(
                    f"Updated {updated} tasks with status {ev} to pending and incremented attempts"
                )

    set_tasks_exhausted(exhausted_total)
    return
