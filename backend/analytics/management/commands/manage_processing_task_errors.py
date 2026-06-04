

import time
from datetime import datetime, timedelta
from typing import Union

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

    def handle(self, *args, **options):
        """
        This command identifies extract tasks that are in an error state (status values specified by --error-values) and resets them to pending (status=0) so they can be reprocessed and increments the attempt count for each task. This allows tasks that may have failed due to transient issues to be retried.
        """
        _manage_processing_task_errors(
            error_values=options["error_values"],
            dry_run=options["dry_run"],
        )


def _manage_processing_task_errors(error_values: Union[int, str], dry_run: bool = False):
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
                        WHERE status = %s
                        """,
                        [ev],
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
                        WHERE status = %s
                        """,
                        [ev],
                    )
                    updated = cursor.rowcount
                    updated = updated if updated is not None else 0  # rowcount can be None in some cases

                    logger.info(
                        f"Updated {updated} tasks with status {ev} to pending and incremented attempts"
                    )

        return
