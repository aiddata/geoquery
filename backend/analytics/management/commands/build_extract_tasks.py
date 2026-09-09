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
# in full every run -- no progress tracking needed here. Non-global datasets
# are always standard (task_group_period IS NULL): grouping only makes sense
# for the time-series-shaped global datasets that drive the (resource, po) x
# feat_map cross below.
_INSERT_NON_GLOBAL_BATCH_SQL = """
    INSERT INTO extract_tasks
        (dataset_id, resource_ids, task_group_period, fm_id, po_id, status, priority, attempts, submit_time)
    SELECT d.id, ARRAY[dr.id], NULL, fm.id, po.id, 0, 0, 0, NOW()
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
      AND d.task_group_period IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM extract_tasks et
          WHERE et.dataset_id = d.id
            AND et.fm_id = fm.id
            AND et.po_id = po.id
            AND et.resource_ids = ARRAY[dr.id]
      )
    LIMIT %s
"""

# Global datasets cover every eligible feature by definition, so the candidate
# space is (resource(s), po) pairs x feat_map -- up to ~12 billion rows. Re-deriving
# and anti-joining that whole space every batch (the original design) meant cost
# grew with how much was already built, not with how much was left: each batch
# had to walk past an ever-growing prefix of already-inserted rows before
# reaching new ones. Instead, extract_task_build_progress tracks completion per
# (resource_ids, po) pair, and each batch is scoped to a single pair's remaining
# feat_map rows -- bounded by feat_map's size (under 1M), not the full cross.
#
# resource_ids is a 1-element array for a standard (ungrouped) dataset (one
# row per individual DatasetResource x po) and an N-element array for a
# grouped dataset (every resource in one date_trunc(task_group_period, ...)
# bucket x po). Either way, each row of extract_task_build_progress is one
# independent unit of work.
#
# Pairs are independent, so this is parallelizable: multiple workers claim
# disjoint pairs via SELECT ... FOR UPDATE SKIP LOCKED and work concurrently.
# See tasks/maintenance.py for the parallel dispatch and the run-lock that
# keeps a slow-but-alive wave of workers from getting duplicated by the next
# scheduled trigger.

_SYNC_STANDARD_PAIRS_SQL = """
    INSERT INTO extract_task_build_progress (resource_ids, po_id)
    SELECT ARRAY[dr.id], po.id
    FROM datasets d
    INNER JOIN dataset_resources dr  ON dr.dataset_id = d.id
    INNER JOIN processing_options po ON po.dataset_id = d.id
    WHERE d.is_global = TRUE AND d.active = TRUE AND po.active = TRUE
      AND d.task_group_period IS NULL
    ON CONFLICT (resource_ids, po_id) DO NOTHING
"""

# Buckets every resource of a grouped dataset by date_trunc(task_group_period,
# temporal) before pairing with its processing options, so each bucket's
# resource_ids array is built once (ARRAY_AGG ... ORDER BY dr.id, matching
# the canonical ascending order the unique index expects) rather than derived
# separately per po.
_SYNC_GROUPED_PAIRS_SQL = """
    INSERT INTO extract_task_build_progress (resource_ids, po_id)
    SELECT bucket.resource_ids, po.id
    FROM (
        SELECT dr.dataset_id, ARRAY_AGG(dr.id ORDER BY dr.id) AS resource_ids
        FROM dataset_resources dr
        INNER JOIN datasets d ON d.id = dr.dataset_id
        WHERE d.is_global = TRUE AND d.active = TRUE AND d.task_group_period IS NOT NULL
        GROUP BY dr.dataset_id, date_trunc(d.task_group_period, dr.temporal)
    ) bucket
    INNER JOIN processing_options po ON po.dataset_id = bucket.dataset_id AND po.active = TRUE
    ON CONFLICT (resource_ids, po_id) DO NOTHING
"""

_MAX_FEAT_MAP_ID_SQL = "SELECT COALESCE(MAX(id), 0) FROM feat_map"

# Fetched/claimed as a page rather than one at a time: if a single pair's
# batch keeps timing out, always re-selecting "the next incomplete pair"
# would retry that same pair forever and block every other pair behind it.
# A whole page per round means one stuck pair can't stall the rest.
PAIRS_PER_ROUND = 50

# How long a pair can sit claimed before another worker treats the claim as
# dead (the claiming worker crashed) and takes it. Comfortably longer than
# one batch's max duration (BATCH_STATEMENT_TIMEOUT_MS).
CLAIM_STALE_MINUTES = 10

# resource_ids[1] is a stand-in for "this pair's dataset": every resource in
# one grouped bucket belongs to the same dataset by construction (both sync
# queries above group/join per dataset before aggregating), so the first
# element always resolves to the right dataset_resources row for the
# dataset_id / task_group_period lookup.
_NEXT_PROGRESS_PAIRS_SQL = """
    SELECT p.id, p.resource_ids, p.po_id, p.completed_up_to_fm_id,
           dr.dataset_id, d.task_group_period
    FROM extract_task_build_progress p
    INNER JOIN dataset_resources dr ON dr.id = p.resource_ids[1]
    INNER JOIN processing_options po ON po.id = p.po_id AND po.dataset_id = dr.dataset_id
    INNER JOIN datasets d ON d.id = dr.dataset_id AND d.is_global = TRUE AND d.active = TRUE
    WHERE po.active = TRUE
      AND (p.completed_up_to_fm_id IS NULL OR p.completed_up_to_fm_id < %(current_max_fm_id)s)
      AND (p.claimed_at IS NULL OR p.claimed_at < NOW() - INTERVAL '{stale_minutes} minutes')
    ORDER BY p.id
    LIMIT %(limit)s
    FOR UPDATE OF p SKIP LOCKED
""".format(stale_minutes=CLAIM_STALE_MINUTES)

_CLAIM_PROGRESS_PAIRS_SQL = """
    UPDATE extract_task_build_progress
    SET claimed_at = NOW()
    WHERE id = ANY(%s)
"""

_RELEASE_CLAIM_SQL = "UPDATE extract_task_build_progress SET claimed_at = NULL WHERE id = %s"

_INSERT_GLOBAL_BATCH_SQL = """
    INSERT INTO extract_tasks
        (dataset_id, resource_ids, task_group_period, fm_id, po_id, status, priority, attempts, submit_time)
    SELECT %(dataset_id)s, %(resource_ids)s, %(task_group_period)s, fm.id, %(po_id)s, 0, 0, 0, NOW()
    FROM feat_map fm
    INNER JOIN feature_collections fc ON fm.fc_id = fc.id
    WHERE fc.active = TRUE
      AND fc.is_user_upload = FALSE
      AND fm.id > %(completed_up_to_fm_id)s
      AND NOT EXISTS (
          SELECT 1 FROM extract_tasks et
          WHERE et.fm_id = fm.id
            AND et.po_id = %(po_id)s
            AND et.resource_ids = %(resource_ids)s
      )
    ORDER BY fm.id
    LIMIT %(batch_size)s
"""

_MARK_PAIR_CAUGHT_UP_SQL = """
    UPDATE extract_task_build_progress
    SET completed_up_to_fm_id = %s, claimed_at = NULL
    WHERE id = %s
"""

# extract_task_build_run is a singleton row coordinating parallel workers so
# a scheduled re-trigger can't launch a fresh wave on top of one still
# grinding through the backlog -- the same unbounded daily pileup that
# caused the original bloat incident, at the task-dispatch level this time.
# in_progress + last_progress_at is a heartbeat, not a fixed timeout: any
# worker's successful batch refreshes it, so "still actively working through
# a big backlog" (frequent heartbeat) is distinguishable from "workers died
# silently" (stale heartbeat) without having to guess how long the backlog
# should take.
RUN_STALE_MINUTES = 30

_TRY_ACQUIRE_RUN_SQL = """
    UPDATE extract_task_build_run
    SET in_progress = TRUE, last_progress_at = NOW()
    WHERE id = 1
      AND (NOT in_progress OR last_progress_at < NOW() - INTERVAL '{stale_minutes} minutes')
    RETURNING TRUE
""".format(stale_minutes=RUN_STALE_MINUTES)

_HEARTBEAT_RUN_SQL = "UPDATE extract_task_build_run SET last_progress_at = NOW() WHERE id = 1"

_RELEASE_RUN_SQL = "UPDATE extract_task_build_run SET in_progress = FALSE WHERE id = 1"

_ANY_INCOMPLETE_PAIRS_SQL = """
    SELECT EXISTS (
        SELECT 1
        FROM extract_task_build_progress p
        INNER JOIN dataset_resources dr ON dr.id = p.resource_ids[1]
        INNER JOIN processing_options po ON po.id = p.po_id AND po.dataset_id = dr.dataset_id
        INNER JOIN datasets d ON d.id = dr.dataset_id AND d.is_global = TRUE AND d.active = TRUE
        WHERE po.active = TRUE
          AND (p.completed_up_to_fm_id IS NULL OR p.completed_up_to_fm_id < %s)
    )
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


def try_acquire_build_run():
    """Claim the singleton run-lock. Returns True if the caller should dispatch
    a fresh wave of parallel workers, False if a previous wave's heartbeat is
    still fresh (already running)."""
    with connection.cursor() as cursor:
        cursor.execute(_TRY_ACQUIRE_RUN_SQL)
        return cursor.fetchone() is not None


def _any_incomplete_pairs(current_max_fm_id):
    with connection.cursor() as cursor:
        cursor.execute(_ANY_INCOMPLETE_PAIRS_SQL, [current_max_fm_id])
        return cursor.fetchone()[0]


def _release_build_run_if_done(current_max_fm_id):
    if not _any_incomplete_pairs(current_max_fm_id):
        with connection.cursor() as cursor:
            cursor.execute(_RELEASE_RUN_SQL)


def _claim_next_progress_pairs(current_max_fm_id, limit):
    """Select the next page of claimable progress pairs and mark them claimed.

    _NEXT_PROGRESS_PAIRS_SQL (SELECT ... FOR UPDATE SKIP LOCKED) and
    _CLAIM_PROGRESS_PAIRS_SQL (the claiming UPDATE) are two separate
    statements rather than one atomic CTE, so SKIP LOCKED is only exclusive
    if both run inside the same transaction.atomic() block -- the assertion
    below protects against a future call site that reuses this pair of
    statements without remembering that wrapper.
    """
    assert transaction.get_connection().in_atomic_block, (
        "must run inside transaction.atomic() -- SELECT ... FOR UPDATE SKIP LOCKED "
        "and the claiming UPDATE must be part of the same transaction, or SKIP LOCKED "
        "loses its exclusivity guarantee"
    )
    with connection.cursor() as cursor:
        cursor.execute(_NEXT_PROGRESS_PAIRS_SQL, {
            "current_max_fm_id": current_max_fm_id,
            "limit": limit,
        })
        pairs = cursor.fetchall()
        if pairs:
            cursor.execute(_CLAIM_PROGRESS_PAIRS_SQL, [[p[0] for p in pairs]])
        return pairs


def _build_global_tasks(batch_size=BATCH_SIZE):
    """One parallel worker's share of the global-dataset backlog.

    Safe to run many of these concurrently: pairs are claimed via
    SELECT ... FOR UPDATE SKIP LOCKED (in the same transaction as the claim
    UPDATE, which is what makes SKIP LOCKED actually exclusive) so concurrent
    workers never claim the same pair, and each pair's batch is independently
    transactional.
    """
    total_added = 0

    with connection.cursor() as cursor:
        cursor.execute(_SYNC_STANDARD_PAIRS_SQL)
        cursor.execute(_SYNC_GROUPED_PAIRS_SQL)
        cursor.execute(_MAX_FEAT_MAP_ID_SQL)
        current_max_fm_id = cursor.fetchone()[0]

    while True:
        with transaction.atomic():
            pairs = _claim_next_progress_pairs(current_max_fm_id, PAIRS_PER_ROUND)

        if not pairs:
            _release_build_run_if_done(current_max_fm_id)
            break

        made_progress = False
        for progress_id, resource_ids, po_id, completed_up_to_fm_id, dataset_id, task_group_period in pairs:
            added = _run_batch(
                _INSERT_GLOBAL_BATCH_SQL,
                {
                    "dataset_id": dataset_id,
                    "resource_ids": resource_ids,
                    "task_group_period": task_group_period,
                    "po_id": po_id,
                    "completed_up_to_fm_id": completed_up_to_fm_id or 0,
                    "batch_size": batch_size,
                },
            )
            if added is None:
                with connection.cursor() as cursor:
                    cursor.execute(_RELEASE_CLAIM_SQL, [progress_id])
                continue  # this pair failed/timed out; try the rest of the page

            made_progress = True
            total_added += added
            with connection.cursor() as cursor:
                cursor.execute(_HEARTBEAT_RUN_SQL)
            logger.info(
                "build_extract_tasks global batch: progress_id=%s resources=%s po=%s added %d (total %d)",
                progress_id, resource_ids, po_id, added, total_added,
            )

            with connection.cursor() as cursor:
                if added < batch_size:
                    cursor.execute(_MARK_PAIR_CAUGHT_UP_SQL, [current_max_fm_id, progress_id])
                else:
                    cursor.execute(_RELEASE_CLAIM_SQL, [progress_id])

        if not made_progress:
            logger.warning(
                "build_extract_tasks: no progress on any of %d claimed pairs this round; "
                "stopping, remainder picked up next run",
                len(pairs),
            )
            break

    return total_added


def _build_non_global_tasks(batch_size=BATCH_SIZE):
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

    Runs both branches in this one process (used by the management command
    and as a non-parallel fallback). The parallel path used in production
    dispatches _build_global_tasks across multiple Celery workers instead --
    see tasks/maintenance.py.
    """
    t_start = time.perf_counter()

    total_added = _build_global_tasks(batch_size) + _build_non_global_tasks(batch_size)

    elapsed = time.perf_counter() - t_start
    logger.info("Generated %d new extract tasks in %.2fs", total_added, elapsed)
    return {"added": total_added, "elapsed": elapsed}
