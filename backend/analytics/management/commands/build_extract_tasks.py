import time
from logging import getLogger
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction
from django.db.models import Case, F, When
from django.db.models.functions import Now

from analytics.models import ExtractTaskBuildProgress, ExtractTaskBuildRun


logger = getLogger(__name__)

# Bounds each insert batch so a single run never holds one long-lived
# transaction (which pins the vacuum horizon and, on the NFS-backed data
# volume, can wedge indefinitely on a stalled write with no way to recover
# short of killing the backend -- see the extract_tasks bloat incident).
BATCH_STATEMENT_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes

# Non-global datasets: gated by a confirmed coverage row (status=1). This
# space is small (bounded by real coverage rows), so it's cheap to re-scan
# in full every run -- no progress tracking needed here. Non-global datasets
# are always standard (task_group_period IS NULL): grouping only makes sense
# for the time-series-shaped global datasets that drive the (resource, po) x
# feat_map cross below.
#
# The NOT EXISTS uses the same task identity as the global batch below; see
# _INSERT_GLOBAL_BATCH_SQL for why kwargs IS NULL and resource_ids_hash are
# there.
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
            AND et.kwargs IS NULL
            AND et.resource_ids_hash = extract_tasks_resource_ids_hash(ARRAY[dr.id])
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
    RETURNING claimed_at
"""

_RELEASE_CLAIM_SQL = "UPDATE extract_task_build_progress SET claimed_at = NULL WHERE id = %s"

# Refreshed right before a pair's own batch starts (see the loop in
# _build_global_tasks), not just once when the whole page was claimed. A
# page holds up to PAIRS_PER_ROUND pairs, each batch can legitimately take
# up to BATCH_STATEMENT_TIMEOUT_MS; a worker slowly working through its own
# page can take far longer than CLAIM_STALE_MINUTES to *reach* a pair near
# the end of that page, even though it's still alive and hasn't abandoned
# it. Without this per-pair touch, claimed_at only reflects "when the page
# was claimed," so a late pair looks stale to other workers long before its
# own worker actually gets to it -- a second worker "rescues" it as if the
# first had died, and both race to insert overlapping rows. Observed in
# production: two different pods both processing the same (resources, po)
# pair, one committing its batch ~12s before the other's failed with a
# duplicate-key IntegrityError on the exact same row.
_TOUCH_CLAIM_SQL = "UPDATE extract_task_build_progress SET claimed_at = NOW() WHERE id = %s"

# The batch advances the pair's watermark in the SAME statement that inserts
# the rows, which is load-bearing rather than tidy. _run_batch commits
# asynchronously, and its safety argument is that a lost batch takes its
# progress with it: if the watermark were written by a separate statement, a
# crash could keep the watermark while losing the async INSERT, and those
# feat_map rows would be skipped forever with nothing to notice. Inside one
# transaction the two are lost or kept together, so the next pass rebuilds
# exactly what was lost.
#
# Before this, the watermark only moved when a pair ran out of work
# (added < batch_size). A pair returning full batches never recorded
# anything, so every batch restarted at fm.id > 0 and re-walked everything it
# had already built -- cost growing with what was done rather than what was
# left, which is precisely what this table exists to prevent. Measured on a
# pair with 695k rows built: 53,248ms and 169.7M buffer hits to find the next
# 5,000 rows, against 621ms and 724k hits when resuming from the watermark.
#
# GREATEST guards the watermark against moving backwards if two workers
# briefly overlap on one pair (see _TOUCH_CLAIM_SQL); the IS NOT NULL guard
# leaves it alone when a batch inserts nothing. Data-modifying CTEs always
# run to completion even when unreferenced, so `advanced` fires regardless of
# what the outer SELECT reads.
#
# The NOT EXISTS matches the task identity the request path uses
# (services._get_or_create_task): kwargs IS NULL and resource_ids_hash are
# what let it seek extract_tasks_fm_po_resources_null_kwargs_idx, a partial
# index Postgres can only use when the query implies its WHERE kwargs IS NULL.
# Without them each probe went through the fm_id index and filtered out every
# other task for that feature -- ~186 rows each on dataset 24. Measured on a
# production replica: 5,000 already-built features took 955k buffer hits and
# ~630ms, against 25k and ~27ms. kwargs IS NULL is also a correctness check:
# without it a task with custom kwargs hid the default task this builds.
# resource_ids is still compared in full, since the hash is only 32 bits.
#
# et.fm_id > %(completed_up_to_fm_id)s changes nothing logically -- it
# already follows from et.fm_id = fm.id and fm.id > the watermark -- but
# Postgres does not carry inequalities across an equality, so without it the
# planner cannot see that the probe only concerns rows past the watermark.
# That matters for a pair being built: its rows postdate the partition's
# statistics, so the planner estimates a handful (19, against 70,000 actual)
# and picks a nested-loop anti join that rescans every row the pair already
# has once per candidate feature. Batch time then grows with the pair's
# progress. Measured on a production replica, pair (ds 24, [3288], po 34)
# with 70k rows built: 24-30s per batch without the bound, ~110ms with it.
# Fully built pairs and empty partitions were unaffected (~45ms, ~3ms).
#
# The ::integer[] casts on %(resource_ids)s are required, not decoration:
# psycopg 3 sends a Python int list as the smallest array type that fits
# (e.g. '{590}'::int2[]), and Postgres has no integer[] = smallint[] operator.
# Without the cast the NOT EXISTS comparison raises, _run_batch swallows the
# DatabaseError, and the build silently inserts nothing.
_INSERT_GLOBAL_BATCH_SQL = """
    WITH inserted AS (
        INSERT INTO extract_tasks
            (dataset_id, resource_ids, task_group_period, fm_id, po_id, status, priority, attempts, submit_time)
        SELECT %(dataset_id)s, %(resource_ids)s::integer[], %(task_group_period)s, fm.id, %(po_id)s, 0, 0, 0, NOW()
        FROM feat_map fm
        INNER JOIN feature_collections fc ON fm.fc_id = fc.id
        WHERE fc.active = TRUE
          AND fc.is_user_upload = FALSE
          AND fm.id > %(completed_up_to_fm_id)s
          AND NOT EXISTS (
              SELECT 1 FROM extract_tasks et
              WHERE et.dataset_id = %(dataset_id)s
                AND et.fm_id = fm.id
                AND et.po_id = %(po_id)s
                AND et.kwargs IS NULL
                AND et.resource_ids_hash = extract_tasks_resource_ids_hash(%(resource_ids)s::integer[])
                AND et.resource_ids = %(resource_ids)s::integer[]
                AND et.fm_id > %(completed_up_to_fm_id)s
          )
        ORDER BY fm.id
        LIMIT %(batch_size)s
        RETURNING fm_id
    ),
    batch AS (
        SELECT count(*) AS added, max(fm_id) AS max_fm_id FROM inserted
    ),
    advanced AS (
        UPDATE extract_task_build_progress p
        SET completed_up_to_fm_id =
                GREATEST(COALESCE(p.completed_up_to_fm_id, 0), batch.max_fm_id)
        FROM batch
        WHERE p.id = %(progress_id)s
          AND batch.max_fm_id IS NOT NULL
        RETURNING p.completed_up_to_fm_id
    )
    SELECT added, max_fm_id FROM batch
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
#
# 10 rather than 30 because this window is what a killed wave waits out before
# anything can rebuild, and 30 was far wider than the heartbeat needs. The
# heartbeat fires after every batch, so the margin is the ratio between the
# two: at the ~112s batches that preceded the per-batch watermark this was
# already ~5x, and at the ~20s batches it produces it is ~30x. Paired with the
# 10-minute beat, worst-case idle after an uncleanly killed wave drops from
# ~90 minutes to ~20.
RUN_STALE_MINUTES = 10

_TRY_ACQUIRE_RUN_SQL = """
    UPDATE extract_task_build_run
    SET in_progress = TRUE, last_progress_at = NOW(),
        run_id = %s, workers_remaining = %s
    WHERE id = 1
      AND (NOT in_progress OR last_progress_at < NOW() - INTERVAL '{stale_minutes} minutes')
    RETURNING run_id
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


def _build_synchronous_commit():
    """Whether build batches wait for fsync. Settable so this can be reverted
    without a deploy if the durability trade is ever unwanted."""
    from django.conf import settings

    return getattr(settings, "EXTRACT_TASK_BUILD_SYNCHRONOUS_COMMIT", False)


def _run_batch(sql, params, fetch=False):
    """Run one INSERT batch in its own short transaction with a statement timeout.

    Returns rows added, or None if the batch failed/timed out (caller stops).
    With fetch=True the statement is expected to return a row and that row is
    returned instead of the rowcount -- the global batch reports its own count
    because its INSERT is wrapped in a CTE, so rowcount would describe the
    outer SELECT rather than the insert.

    Commits asynchronously by default (SET LOCAL, so it applies to this
    transaction only -- not to anything else this role does). The database is
    write-bandwidth bound: backends queue on the WALWrite lock, and these
    5000-row batches are the largest single contributor. synchronous_commit
    = off takes them out of the fsync path entirely -- the rows land in the
    WAL buffer and the walwriter flushes them behind us -- so the batch stops
    waiting on storage itself. Its WAL still has to be flushed, though, and
    the next commit that waits for fsync waits for that too: this moves the
    builder's flush cost onto other writers rather than removing it.

    Safe specifically here because the work is regenerable. An unclean crash
    can lose up to ~3 x wal_writer_delay (~600ms) of recently committed
    batches; those are speculative extract_tasks rows, and
    completed_up_to_fm_id simply will not have advanced for them, so the next
    pass rebuilds exactly what was lost. Processing commits asynchronously as
    well, on its own reasoning -- see EXTRACT_TASK_SYNCHRONOUS_COMMIT.
    """
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [BATCH_STATEMENT_TIMEOUT_MS])
                if not _build_synchronous_commit():
                    cursor.execute("SET LOCAL synchronous_commit = off")
                cursor.execute(sql, params)
                return cursor.fetchone() if fetch else cursor.rowcount
    except DatabaseError:
        logger.exception("build_extract_tasks batch failed/timed out")
        return None


def try_acquire_build_run(worker_count=1):
    """Return a new wave's UUID, or None while a healthy wave is running.

    The existing stale heartbeat also reaps the worker count after a crash.
    """
    with connection.cursor() as cursor:
        cursor.execute(_TRY_ACQUIRE_RUN_SQL, [uuid4(), worker_count])
        row = cursor.fetchone()
        return row[0] if row else None


def finish_build_worker(run_id):
    # The last worker releases the wave even when capped with work still
    # left. A late worker from a reaped wave cannot finish a replacement.
    ExtractTaskBuildRun.objects.filter(pk=1, run_id=run_id, workers_remaining__gt=0).update(
        workers_remaining=F("workers_remaining") - 1,
        in_progress=Case(When(workers_remaining__gt=1, then=True), default=False),
    )


def _heartbeat_build_run(run_id):
    if run_id is None:
        with connection.cursor() as cursor:
            cursor.execute(_HEARTBEAT_RUN_SQL)
        return True
    return bool(
        ExtractTaskBuildRun.objects.filter(pk=1, run_id=run_id, in_progress=True).update(last_progress_at=Now())
    )


def _release_unstarted_claims(pair_ids, claimed_at):
    # Clear only claims still belonging to this page; a delayed worker must
    # not clear a replacement's claims after CLAIM_STALE_MINUTES.
    ExtractTaskBuildProgress.objects.filter(pk__in=pair_ids, claimed_at=claimed_at).update(claimed_at=None)


def _build_limits(batch_size, max_tasks):
    batch_size = settings.EXTRACT_TASK_BUILD_BATCH_SIZE if batch_size is None else batch_size
    max_tasks = settings.EXTRACT_TASK_BUILD_MAX_TASKS if max_tasks is None else max_tasks
    if batch_size < 1 or max_tasks < 0:
        raise ValueError("batch_size must be positive and max_tasks must be nonnegative")
    return batch_size, max_tasks


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
            claimed_at = cursor.fetchone()[0]
            pairs = [(*p, claimed_at) for p in pairs]
        return pairs


def _build_global_tasks(batch_size=None, max_tasks=None, run_id=None):
    """One parallel worker's share of the global-dataset backlog.

    Safe to run many of these concurrently: pairs are claimed via
    SELECT ... FOR UPDATE SKIP LOCKED (in the same transaction as the claim
    UPDATE, which is what makes SKIP LOCKED actually exclusive) so concurrent
    workers never claim the same pair, and each pair's batch is independently
    transactional.

    max_tasks counts newly inserted rows, not candidates or batches. A
    shortened final batch must not mark a pair caught up if it hit its limit.
    """
    batch_size, max_tasks = _build_limits(batch_size, max_tasks)
    total_added = 0

    with connection.cursor() as cursor:
        cursor.execute(_SYNC_STANDARD_PAIRS_SQL)
        cursor.execute(_SYNC_GROUPED_PAIRS_SQL)
        cursor.execute(_MAX_FEAT_MAP_ID_SQL)
        current_max_fm_id = cursor.fetchone()[0]

    while not max_tasks or total_added < max_tasks:
        if run_id is not None and not _heartbeat_build_run(run_id):
            break
        with transaction.atomic():
            pairs = _claim_next_progress_pairs(current_max_fm_id, PAIRS_PER_ROUND)

        if not pairs:
            if run_id is None:
                _release_build_run_if_done(current_max_fm_id)
            break

        made_progress = False
        unstarted = {p[0] for p in pairs}
        try:
            for (
                progress_id, resource_ids, po_id, completed_up_to_fm_id,
                dataset_id, task_group_period, _claimed_at,
            ) in pairs:
                if max_tasks and total_added >= max_tasks:
                    break
                if run_id is not None and not _heartbeat_build_run(run_id):
                    break
                unstarted.remove(progress_id)
                insert_limit = min(batch_size, max_tasks - total_added) if max_tasks else batch_size
                with connection.cursor() as cursor:
                    cursor.execute(_TOUCH_CLAIM_SQL, [progress_id])
                result = _run_batch(
                    _INSERT_GLOBAL_BATCH_SQL,
                    {
                        "dataset_id": dataset_id,
                        "resource_ids": resource_ids,
                        "task_group_period": task_group_period,
                        "po_id": po_id,
                        "completed_up_to_fm_id": completed_up_to_fm_id or 0,
                        "batch_size": insert_limit,
                        "progress_id": progress_id,
                    },
                    fetch=True,
                )
                if result is None:
                    with connection.cursor() as cursor:
                        cursor.execute(_RELEASE_CLAIM_SQL, [progress_id])
                    continue  # this pair failed/timed out; try the rest of the page

                # The statement already advanced the watermark atomically.
                added, _max_fm_id = result
                made_progress = True
                total_added += added
                _heartbeat_build_run(run_id)
                logger.info(
                    "build_extract_tasks global batch: progress_id=%s resources=%s po=%s added %d (total %d)",
                    progress_id, resource_ids, po_id, added, total_added,
                )

                with connection.cursor() as cursor:
                    if added < insert_limit:
                        cursor.execute(_MARK_PAIR_CAUGHT_UP_SQL, [current_max_fm_id, progress_id])
                    else:
                        cursor.execute(_RELEASE_CLAIM_SQL, [progress_id])
        finally:
            if unstarted:
                _release_unstarted_claims(unstarted, pairs[0][-1])

        if not made_progress:
            logger.warning(
                "build_extract_tasks: no progress on any of %d claimed pairs this round; "
                "stopping, remainder picked up next run",
                len(pairs),
            )
            break

    return total_added


def _build_non_global_tasks(batch_size=None, max_tasks=None):
    batch_size, max_tasks = _build_limits(batch_size, max_tasks)
    total_added = 0
    while not max_tasks or total_added < max_tasks:
        insert_limit = min(batch_size, max_tasks - total_added) if max_tasks else batch_size
        added = _run_batch(_INSERT_NON_GLOBAL_BATCH_SQL, [insert_limit])
        if added is None:
            break
        total_added += added
        logger.info("build_extract_tasks non-global batch: added %d (total %d)", added, total_added)
        if added < insert_limit:
            break
    return total_added


def _build_extract_tasks(batch_size=None, max_tasks=None):
    """Create ExtractTask rows for covered dataset/feature pairs that don't have one yet.

    Runs both branches in this one process (used by the management command
    and as a non-parallel fallback). The parallel path used in production
    dispatches _build_global_tasks across multiple Celery workers instead --
    see tasks/maintenance.py.
    """
    t_start = time.perf_counter()
    batch_size, max_tasks = _build_limits(batch_size, max_tasks)
    total_added = _build_global_tasks(batch_size, max_tasks)
    if not max_tasks or total_added < max_tasks:
        remaining = max_tasks - total_added if max_tasks else 0
        total_added += _build_non_global_tasks(batch_size, remaining)

    elapsed = time.perf_counter() - t_start
    logger.info("Generated %d new extract tasks in %.2fs", total_added, elapsed)
    return {"added": total_added, "elapsed": elapsed}
