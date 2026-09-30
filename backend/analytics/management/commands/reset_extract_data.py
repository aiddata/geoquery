import sys
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import connection


logger = getLogger(__name__)

# extract_tasks is LIST partitioned on dataset_id. Resetting per-partition
# keeps each statement's dead-tuple footprint to one partition instead of
# rewriting ~347M rows in a single transaction -- roughly 48 GB of dead heap,
# plus the pending partial index growing from 258.9M to 606M entries.
#
# Partitions are discovered via pg_inherits (actual children of the
# extract_tasks parent) rather than a name pattern like 'extract_tasks_ds%':
# migration 0021 gives every Dataset existing at migration time its own
# extract_tasks_ds_<id> partition, but per that migration's own docstring
# there is no mechanism that creates a new per-dataset partition when a
# Dataset is created afterward -- those rows land in the catch-all
# extract_tasks_default partition instead, indefinitely. A name-based filter
# would silently skip that partition (and every dataset added since the
# migration ran); pg_inherits can't miss it.
_PARTITIONS_SQL = """
    SELECT c.relname
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    WHERE i.inhparent = 'extract_tasks'::regclass
    ORDER BY c.relname
"""

_COUNT_SQL = "SELECT count(*) FROM {table} WHERE status <> 0"

# complete_time, attempts and error are cleared alongside status so a reset
# task is indistinguishable from one that has never run. A stale complete_time
# left behind would keep the task in stats/builder.py's completions chart while
# it sits pending.
_RESET_SQL = """
    UPDATE {table}
    SET status = 0, complete_time = NULL, attempts = 0, error = NULL
    WHERE status <> 0
"""


class Command(BaseCommand):
    help = (
        "Discard every extract_data row and return processed extract tasks to "
        "pending, so they are re-extracted into the current schema."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually do it. Without this the command refuses.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be reset, per partition, and change nothing.",
        )

    def handle(self, *_args, **options):
        if not options["dry_run"] and not options["confirm"]:
            self.stderr.write(
                self.style.ERROR(
                    "Refusing to run without --confirm. This TRUNCATEs extract_data "
                    "and resets every processed extract task to pending. The data is "
                    "regenerable, but re-extracting it costs days of fleet capacity."
                )
            )
            sys.exit(1)

        # VACUUM cannot run inside a transaction block.
        connection.set_autocommit(True)

        with connection.cursor() as cursor:
            cursor.execute(_PARTITIONS_SQL)
            partitions = [r[0] for r in cursor.fetchall()]

        if options["dry_run"]:
            total = 0
            with connection.cursor() as cursor:
                for table in partitions:
                    cursor.execute(_COUNT_SQL.format(table=table))
                    n = cursor.fetchone()[0]
                    total += n
                    if n:
                        self.stdout.write(f"{table}: would reset {n:,} tasks")
            self.stdout.write(
                self.style.WARNING(
                    f"dry run: {total:,} tasks across {len(partitions)} partitions"
                )
            )
            return

        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE extract_data")
        self.stdout.write(self.style.SUCCESS("extract_data truncated"))

        total = 0
        for table in partitions:
            with connection.cursor() as cursor:
                cursor.execute(_RESET_SQL.format(table=table))
                n = cursor.rowcount
                total += n
                # Vacuum between partitions, not once at the end: the point is
                # to stop one partition's dead tuples accumulating across all
                # 57 of them at once.
                cursor.execute(f"VACUUM {table}")
            if n:
                self.stdout.write(f"{table}: reset {n:,} tasks, vacuumed")
            logger.info("reset_extract_data: %s reset %d tasks", table, n)

        self.stdout.write(
            self.style.SUCCESS(
                f"reset {total:,} tasks across {len(partitions)} partitions"
            )
        )
