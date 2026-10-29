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


# extract_tasks.error is capped at 100 characters and comes in three shapes:
#
#   resource 12[0]: RasterioIOError('/data/...'); resource 13[1]: ...
#       a feature that failed on one or more resources (processing and
#       leases._failure_summary)
#   setup: missing resources [12, 13]
#       a lease that could not load its inputs at all (leases._compute_lease)
#   RasterioIOError('/data/...')
#       a bare repr(exc), from a request task's chunk failing outright
#
# Only the first exception's class name becomes a metric label -- the rest is
# a message carrying file paths and coordinates, which would make the label
# unbounded. The full text still goes to the log.
_RESOURCE_PREFIX = re.compile(r"resource \d+\[\d+\]: ")
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
    if error.startswith("setup: "):
        return "setup"
    prefix = _RESOURCE_PREFIX.match(error)
    if prefix:
        error = error[prefix.end():]
    match = _EXCEPTION_CLASS.match(error)
    return match.group(0)[:60] if match else "unparsed"


class Command(BaseCommand):
    help = "Return errored extract tasks to pending, up to MAX_EXTRACT_TASK_ATTEMPTS"

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
    at status = -1: _check_request_tasks counts it as failed and the request
    holding it is failed instead of waiting on it indefinitely. A lease writes
    a feature that ran out of page assignments at the limit directly
    (leases._fail_terminally), so it never comes through here as a retry.

    Both statements name attempts as well as status so they can use
    extract_tasks_errored_idx (migration 0029), which is keyed on attempts
    precisely because exhausted tasks stay at -1 forever -- without the key
    the sweep would re-read all of them on every run.

    This is also where a failure is recorded. Every failure that is retried
    passes through here exactly once, either retried or (a retired pair's,
    which nothing can claim) deleted, and either way its `error` is gone
    afterwards -- a retry overwrites it with NULL. (The other way out of the
    error status is a sync reset after an input change, which recomputes the
    task against new inputs; that is not a retry and is not counted.) The
    exception class goes to a counter and the full text to the log.
    Deliberately not instrumented in the workers instead -- they compute
    thousands of features a second, this runs every ten minutes over a
    handful of rows.
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
            # never retried again: a request holding one fails, and a
            # background feature stays without a value until its inputs
            # change. This number is the one place that shows how many.
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
                # A retired pair's failure that no request needs could never
                # be claimed again (see extract_runnable_tasks). Delete it
                # instead of queueing it: if its pair is reactivated, the
                # cursor restarts at 0 and a lease computes it afresh.
                cursor.execute(
                    """
                        WITH doomed AS (
                            SELECT t.dataset_id, t.id FROM extract_tasks t
                            WHERE t.status = %s AND t.attempts < %s
                              AND t.pair_id IS NOT NULL
                              AND NOT EXISTS (SELECT 1 FROM extract_task_build_progress p
                                              WHERE p.id = t.pair_id AND p.current)
                              AND NOT EXISTS (SELECT 1 FROM request_map rm
                                              WHERE rm.dataset_id = t.dataset_id AND rm.task_id = t.id)
                        ), results AS (
                            DELETE FROM extract_data d USING doomed
                            WHERE d.dataset_id = doomed.dataset_id AND d.extract_task_id = doomed.id
                        )
                        DELETE FROM extract_tasks t USING doomed
                        WHERE t.dataset_id = doomed.dataset_id AND t.id = doomed.id
                        RETURNING t.error
                        """,
                    [ev, max_attempts],
                )
                discarded = [row[0] for row in cursor.fetchall()]
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

                by_exception = Counter(_exception_class(error) for error in discarded)
                if discarded:
                    logger.info(
                        f"Deleted {len(discarded)} failed task(s) with status {ev} "
                        f"of retired pairs instead of retrying them"
                    )
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
                record_work("tasks_discarded", len(discarded))
                logger.info(
                    f"Updated {updated} tasks with status {ev} to pending and incremented attempts"
                )

    set_tasks_exhausted(exhausted_total)
    return
