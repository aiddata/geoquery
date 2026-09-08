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

# Non-global datasets: gated by a confirmed coverage row (status=1). This
# space is small (bounded by real coverage rows), so it's cheap to re-scan
# in full every run -- no progress tracking needed here.
_INSERT_NON_GLOBAL_BATCH_SQL = """
    INSERT INTO extract_tasks
        (resource_id, fm_id, po_id, status, priority, attempts, submit_time)
    SELECT dr.id, fm.id, po.id, 0, 0, 0, NOW()
    FROM coverage
    INNER JOIN feat_map fm            ON coverage.geom_id = fm.geom_id
    INNER JOIN feature_collections fc ON fm.fc_id = fc.id
    INNER JOIN dataset_resources dr   ON coverage.dataset_id = dr.dataset_id
    INNER JOIN processing_options po  ON coverage.dataset_id = po.dataset_id
    INNER JOIN datasets d             ON coverage.dataset_id = d.id
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

# Global datasets cover every eligible feature by definition, so the candidate
# space is (resource, po) pairs x feat_map -- up to ~12 billion rows. Re-deriving
# and anti-joining that whole space every batch (the original design) meant cost
# grew with how much was already built, not with how much was left: each batch
# had to walk past an ever-growing prefix of already-inserted rows before
# reaching new ones. Instead, extract_task_build_progress tracks completion per
# (resource, po) pair, and each batch is scoped to a single pair's remaining
# feat_map rows -- bounded by feat_map's size (under 1M), not the full cross.

_SYNC_PROGRESS_PAIRS_SQL = """
    INSERT INTO extract_task_build_progress (resource_id, po_id)
    SELECT dr.id, po.id
    FROM datasets d
    INNER JOIN dataset_resources dr  ON dr.dataset_id = d.id
    INNER JOIN processing_options po ON po.dataset_id = d.id
    WHERE d.is_global = TRUE AND d.active = TRUE AND po.active = TRUE
    ON CONFLICT (resource_id, po_id) DO NOTHING
"""

_MAX_FEAT_MAP_ID_SQL = "SELECT COALESCE(MAX(id), 0) FROM feat_map"

# Fetched as a page rather than one at a time: if a single pair's batch keeps
# timing out, always re-selecting "the next incomplete pair" would retry that
# same pair forever and block every other pair behind it. Trying a whole page
# per round means one stuck pair can't stall the rest.
PAIRS_PER_ROUND = 50

_NEXT_PROGRESS_PAIRS_SQL = """
    SELECT p.resource_id, p.po_id, p.completed_up_to_fm_id
    FROM extract_task_build_progress p
    INNER JOIN dataset_resources dr ON dr.id = p.resource_id
    INNER JOIN processing_options po ON po.id = p.po_id AND po.dataset_id = dr.dataset_id
    INNER JOIN datasets d ON d.id = dr.dataset_id AND d.is_global = TRUE AND d.active = TRUE
    WHERE po.active = TRUE
      AND (p.completed_up_to_fm_id IS NULL OR p.completed_up_to_fm_id < %s)
    ORDER BY p.resource_id, p.po_id
    LIMIT %s
"""

_INSERT_GLOBAL_PAIR_BATCH_SQL = """
    INSERT INTO extract_tasks
        (resource_id, fm_id, po_id, status, priority, attempts, submit_time)
    SELECT %(resource_id)s, fm.id, %(po_id)s, 0, 0, 0, NOW()
    FROM feat_map fm
    INNER JOIN feature_collections fc ON fm.fc_id = fc.id
    WHERE fc.active = TRUE
      AND fc.is_user_upload = FALSE
      AND fm.id > %(completed_up_to_fm_id)s
      AND NOT EXISTS (
          SELECT 1 FROM extract_tasks et
          WHERE et.resource_id = %(resource_id)s
            AND et.fm_id = fm.id
            AND et.po_id = %(po_id)s
      )
    ORDER BY fm.id
    LIMIT %(batch_size)s
"""

_MARK_PAIR_CAUGHT_UP_SQL = """
    UPDATE extract_task_build_progress
    SET completed_up_to_fm_id = %s
    WHERE resource_id = %s AND po_id = %s
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


def _run_batch(sql, params):
    """Run one INSERT batch in its own short transaction with a statement timeout.

    Returns rows added, or None if the batch failed/timed out (caller stops).
    """
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [BATCH_STATEMENT_TIMEOUT_MS])
                cursor.execute(sql, params)
                return cursor.rowcount
    except DatabaseError:
        logger.exception("build_extract_tasks batch failed/timed out")
        return None


def _build_global_tasks(batch_size):
    total_added = 0

    with connection.cursor() as cursor:
        cursor.execute(_SYNC_PROGRESS_PAIRS_SQL)
        cursor.execute(_MAX_FEAT_MAP_ID_SQL)
        current_max_fm_id = cursor.fetchone()[0]

    while True:
        with connection.cursor() as cursor:
            cursor.execute(_NEXT_PROGRESS_PAIRS_SQL, [current_max_fm_id, PAIRS_PER_ROUND])
            pairs = cursor.fetchall()
        if not pairs:
            break

        made_progress = False
        for resource_id, po_id, completed_up_to_fm_id in pairs:
            added = _run_batch(
                _INSERT_GLOBAL_PAIR_BATCH_SQL,
                {
                    "resource_id": resource_id,
                    "po_id": po_id,
                    "completed_up_to_fm_id": completed_up_to_fm_id or 0,
                    "batch_size": batch_size,
                },
            )
            if added is None:
                continue  # this pair failed/timed out; try the rest of the page

            made_progress = True
            total_added += added
            logger.info(
                "build_extract_tasks global batch: resource=%s po=%s added %d (total %d)",
                resource_id, po_id, added, total_added,
            )

            if added < batch_size:
                with connection.cursor() as cursor:
                    cursor.execute(_MARK_PAIR_CAUGHT_UP_SQL, [current_max_fm_id, resource_id, po_id])

        if not made_progress:
            logger.warning(
                "build_extract_tasks: no progress on any of %d fetched pairs this round; "
                "stopping, remainder picked up next run",
                len(pairs),
            )
            break

    return total_added


def _build_non_global_tasks(batch_size):
    total_added = 0
    while True:
        added = _run_batch(_INSERT_NON_GLOBAL_BATCH_SQL, [batch_size])
        if added is None:
            break
        total_added += added
        logger.info("build_extract_tasks non-global batch: added %d (total %d)", added, total_added)
        if added < batch_size:
            break
    return total_added


def _build_extract_tasks(batch_size=BATCH_SIZE):
    """Create ExtractTask rows for covered dataset/feature pairs that don't have one yet.

    Global-dataset tasks are generated per (resource, po) pair, tracked in
    extract_task_build_progress so repeat runs only look at feat_map rows added
    since a pair was last caught up. Non-global tasks (gated by coverage) stay a
    plain batched scan since that space is small. Every batch is its own short
    transaction with a timeout, so a stall only costs one batch, not the run.
    """
    t_start = time.perf_counter()

    total_added = _build_global_tasks(batch_size) + _build_non_global_tasks(batch_size)

    elapsed = time.perf_counter() - t_start
    logger.info("Generated %d new extract tasks in %.2fs", total_added, elapsed)
    return {"added": total_added, "elapsed": elapsed}
