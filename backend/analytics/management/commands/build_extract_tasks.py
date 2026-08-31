import time
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction


logger = getLogger(__name__)

# Bounds each insert batch so a single run never holds one long-lived
# transaction (which pins the vacuum horizon and, on the NFS-backed data
# volume, can wedge indefinitely on a stalled write with no way to recover
# short of killing the backend -- see the extract_tasks bloat incident).
BATCH_SIZE = 5000
BATCH_STATEMENT_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes

_INSERT_BATCH_SQL = """
    INSERT INTO extract_tasks
        (resource_id, fm_id, po_id, status, priority, attempts, submit_time)
    SELECT
        dr.id,
        fm.id,
        po.id,
        0, 0, 0, NOW()
    FROM coverage
    INNER JOIN feat_map fm
        ON coverage.geom_id = fm.geom_id
    INNER JOIN feature_collections fc
        ON fm.fc_id = fc.id
    INNER JOIN dataset_resources dr
        ON coverage.dataset_id = dr.dataset_id
    INNER JOIN processing_options po
        ON coverage.dataset_id = po.dataset_id
    INNER JOIN datasets d
        ON coverage.dataset_id = d.id
    WHERE coverage.status = 1
      AND po.active = TRUE
      AND fc.active = TRUE
      AND fc.is_user_upload = FALSE
      AND d.active = TRUE
      AND NOT EXISTS (
          SELECT 1 FROM extract_tasks et
          WHERE et.resource_id = dr.id
            AND et.fm_id = fm.id
            AND et.po_id = po.id
      )
    LIMIT %s
"""


class Command(BaseCommand):
    help = "Create ExtractTask rows for covered dataset/feature pairs that don't have one yet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            default=False,
            help="Whether to overwrite existing extract tasks (not yet implemented)",
        )

    def handle(self, *_args, **_options):
        result = _build_extract_tasks()
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {result['added']} new extract tasks in {result['elapsed']:.2f}s"
            )
        )


def _build_extract_tasks(batch_size=BATCH_SIZE):
    """Create ExtractTask rows for covered dataset/feature pairs that don't have one yet.

    Runs in bounded batches, each its own short transaction, rather than one
    unbatched INSERT...SELECT. If a batch stalls past BATCH_STATEMENT_TIMEOUT_MS
    it is cancelled and rolled back; rows from prior batches stay committed, and
    the remaining candidates are picked up by the next scheduled run (the
    NOT EXISTS check makes this idempotent).
    """
    t_start = time.perf_counter()
    total_added = 0

    while True:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SET LOCAL statement_timeout = %s", [BATCH_STATEMENT_TIMEOUT_MS]
                    )
                    cursor.execute(_INSERT_BATCH_SQL, [batch_size])
                    added = cursor.rowcount
        except DatabaseError:
            logger.exception(
                "build_extract_tasks batch failed/timed out after adding %d so far; "
                "stopping this run, remainder will be picked up next run",
                total_added,
            )
            break

        total_added += added
        logger.info("build_extract_tasks batch: added %d (total %d)", added, total_added)

        if added < batch_size:
            break

    elapsed = time.perf_counter() - t_start
    logger.info("Generated %d new extract tasks in %.2fs", total_added, elapsed)
    return {"added": total_added, "elapsed": elapsed}
