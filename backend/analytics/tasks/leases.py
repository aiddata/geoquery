"""Pair cursor leases: background extraction that creates task rows when it finishes.

A worker slot with no pending task rows to run leases a page of features
from one pair's cursor, computes the page with no transaction open, then
inserts the finished task rows and their results and deletes the lease in one
synchronous transaction. Requests, retries and request tasks sync resets keep
using task rows (analytics.tasks.processing).

A page holds at most EXTRACT_TASK_LEASE_PAGE_SIZE features, and fewer for a
slow pair: each pair keeps a moving average of its compute time per feature,
and pages aim at EXTRACT_TASK_LEASE_PAGE_SECONDS of work (see _page_size).

    claim     one short transaction: guards, pair lock, scan one window of
              the cursor, INSERT the lease, advance the cursor
    load      option, ordered resources and category map once; geometries
              in blocks, optionally from a standby after a WAL barrier
    compute   block-major, resource-minor; batch processors open each
              raster once per block
    complete  guards, lease lock and token check, INSERT tasks
              ON CONFLICT DO NOTHING, COPY results, DELETE lease

Invariants this module maintains (see ExtractTaskBuildProgress and
ExtractTaskLease for the rest):

- The cursor moves only in the transaction that creates the lease covering
  what it passed, or past features that need nothing: an existing task, a
  feature outside coverage, an ineligible collection (whose reactivation
  rewinds), a feature a pending targeted reset names, or a collection being
  reset as a whole above its rewind_from. Publishing those changes rewinds
  the cursor below what they cover.
- Every write to a lease is fenced on its token under the lease's row lock.
- A lease is deleted only by its completion (or terminal failure), by sync
  when its pair is retired, or when every member feature was deleted.
- Recovery is bounded. Expiry detects a lost worker; three unsuccessful
  assignments split a page in half, down to single features; a single
  feature gets MAX_EXTRACT_TASK_ATTEMPTS assignments before it becomes a
  terminal failed task. Infrastructure failures refund the assignment and
  back off instead of poisoning features.
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from warnings import catch_warnings

import shapely
from django.conf import settings
from django.db import (
    DataError, IntegrityError, InterfaceError, OperationalError, connection,
    connections, transaction,
)

from analytics import metrics
from analytics.changes import UNAVAILABLE_SQL, Generations, InputStateMissing, lock_states, recheck
from analytics.coverage import barrier_for
from analytics.tasks.processing import (
    _COPY_RESULTS, _failure_summary, _op_kwargs, _result_rows, get_batch_func, get_func,
)

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 60 * 1000
LOCK_TIMEOUT_MS = 5 * 1000
# Back off a pair whose page collided with a different resource array on the
# 32-bit hash. Rare enough that a fixed, visible delay is the right shape.
PAIR_ERROR_BACKOFF_SECONDS = 300
# Stop computing this long before the lease expires, so the completion can
# still commit under the current token.
EXPIRY_MARGIN_SECONDS = 60
# SQLSTATEs meaning "this value cannot be stored": string too long, numeric
# out of range, invalid text representation, and an untranslatable character.
STORAGE_SQLSTATES = frozenset({"22001", "22003", "22P02", "22021"})


@dataclass
class Lease:
    id: int
    token: uuid.UUID
    progress_id: int
    dataset_id: int
    resource_ids: list[int]
    po_id: int
    task_group_period: str | None
    fm_ids: list[int]
    generations: Generations
    attempts: int
    assigned_at: float = field(default_factory=time.monotonic)
    takeover: bool = False

    @property
    def deadline(self):
        """Monotonic time by which computation must stop."""
        return self.assigned_at + settings.EXTRACT_TASK_LEASE_SECONDS - EXPIRY_MARGIN_SECONDS


class AbandonPage(Exception):
    """Computation stopped before the page finished; return the lease.

    ``refund`` is True when the assignment should not count against the
    page (a graceful stop); False when the page itself ran too long.
    """

    def __init__(self, reason, refund):
        super().__init__(reason)
        self.reason = reason
        self.refund = refund


class _PairCollision(Exception):
    """A task with the same hash key but a different resource array exists."""


def _page_target_seconds():
    """How long a page should take to compute.

    A worker slot looks for request tasks only between units of work, so a
    page's duration is how long a new request can wait behind background
    extraction. EXTRACT_TASK_LEASE_PAGE_SECONDS keeps that short; a quarter
    of the lease still bounds it, leaving room before a takeover.
    """
    return min(settings.EXTRACT_TASK_LEASE_PAGE_SECONDS, settings.EXTRACT_TASK_LEASE_SECONDS / 4)


def _page_size(seconds_per_feature, resources):
    """Features per page for a pair: the target duration at its observed pace.

    Before any page has finished, assume time grows with the resources each
    task reads, so a twelve-resource grouped pair starts at a twelfth.
    """
    cap = settings.EXTRACT_TASK_LEASE_PAGE_SIZE
    if seconds_per_feature:
        return max(1, min(cap, int(_page_target_seconds() / seconds_per_feature)))
    return max(1, cap // max(1, resources))


def _record_pace(lease, seconds_per_feature, *, at_least=False):
    """Fold a page's pace into its pair's average, best effort and after commit.

    Never inside a completion: a publish holds pair locks while it waits for
    lease locks, so a completion waiting on its pair could deadlock with it.
    ``at_least`` records a lower bound (a page that ran out of time).
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE extract_task_build_progress SET seconds_per_feature = CASE
                    WHEN %(at_least)s THEN GREATEST(COALESCE(seconds_per_feature, 0), %(pace)s)
                    WHEN seconds_per_feature IS NULL THEN %(pace)s
                    ELSE 0.7 * seconds_per_feature + 0.3 * %(pace)s END
                WHERE id = (SELECT id FROM extract_task_build_progress
                            WHERE id = %(pair)s FOR UPDATE SKIP LOCKED)
                """,
                {"at_least": at_least, "pace": seconds_per_feature, "pair": lease.progress_id},
            )
    except Exception:
        logger.warning("Could not record the pace of pair %s", lease.progress_id, exc_info=True)


def _timeouts(cursor):
    cursor.execute(
        "SET LOCAL statement_timeout = %s; SET LOCAL lock_timeout = %s",
        [STATEMENT_TIMEOUT_MS, LOCK_TIMEOUT_MS],
    )


def _leases_enabled():
    return settings.EXTRACT_TASK_LEASES_ENABLED


# -- claim ---------------------------------------------------------------------


def claim_lease():
    """Assign this worker one page: a due lease first, else a new page.

    Returns a Lease or None. Every attempt runs in its own short
    transaction; no lock survives this call.
    """
    if not _leases_enabled():
        return None
    started = time.perf_counter()
    try:
        lease = _take_over_due_lease() or _lease_new_page()
    finally:
        metrics.LEASE_PHASE_SECONDS.labels("claim").observe(time.perf_counter() - started)
    return lease


# A pair none of whose inputs a pending targeted reset names. Its leases and
# pages wait until sync has reset the affected tasks and published.
_PAIR_VALID = """
    NOT EXISTS (
        SELECT 1 FROM extract_invalid_items i
        WHERE i.scope_kind = 'dataset' AND i.scope_id = p.dataset_id
          AND ((i.item_kind = 'option' AND i.item_id = p.po_id)
               OR (i.item_kind = 'resource' AND i.item_id = ANY(p.resource_ids))))
"""

# Leases whose owner has gone (expired) and whose backoff has passed, of a
# current pair whose dataset is available and whose dataset and option are
# active, with no member a pending reset names. Parked leases (inactive
# dataset or option) are left alone; retired pairs' leases are deleted by
# sync; the rest wait for their publish, which re-tokens them.
_DUE_LEASES_SQL = f"""
    SELECT l.id
    FROM extract_task_leases l
    JOIN extract_task_build_progress p ON p.id = l.progress_id AND p.current
    JOIN datasets d ON d.id = l.dataset_id AND d.active
    JOIN processing_options po ON po.id = l.po_id AND po.active
    JOIN extract_input_state s
      ON s.kind = 'dataset' AND s.object_id = l.dataset_id AND NOT {UNAVAILABLE_SQL}
    WHERE l.leased_until <= now() AND l.retry_after <= now()
      AND {_PAIR_VALID}
      AND NOT EXISTS (SELECT 1 FROM extract_invalid_items i
                      WHERE i.item_kind = 'feature' AND i.item_id = ANY(l.fm_ids))
    ORDER BY l.leased_until, l.id
    LIMIT 16
"""


def _take_over_due_lease():
    with connection.cursor() as cursor:
        cursor.execute(_DUE_LEASES_SQL)
        candidates = [r[0] for r in cursor.fetchall()]
    random.shuffle(candidates)
    for lease_id in candidates:
        lease = _try_take_over(lease_id)
        if lease is not None:
            return lease
    return None


def _members(cursor, fm_ids):
    """``{fm_id: fc_id}`` for the features that still exist (read on the primary)."""
    cursor.execute("SELECT id, fc_id FROM feat_map WHERE id = ANY(%s::int[])", [fm_ids])
    return dict(cursor.fetchall())


def _try_take_over(lease_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT dataset_id, fm_ids FROM extract_task_leases WHERE id = %s", [lease_id]
        )
        row = cursor.fetchone()
        if row is None:
            return None
        dataset_id, fm_ids = row
        members = _members(cursor, fm_ids)

    with transaction.atomic():
        with connection.cursor() as cursor:
            _timeouts(cursor)
            try:
                guard = lock_states([dataset_id], set(members.values()), cursor=cursor)
            except InputStateMissing:
                logger.exception("Lease %s names a scope with no input state", lease_id)
                return None
            if not guard.all_clean:
                return None
            cursor.execute(
                """
                SELECT l.progress_id, l.resource_ids, l.po_id, l.task_group_period,
                       l.fm_ids, l.attempts, l.last_error, p.seconds_per_feature
                FROM extract_task_leases l
                JOIN extract_task_build_progress p ON p.id = l.progress_id AND p.current
                JOIN datasets d ON d.id = l.dataset_id AND d.active
                JOIN processing_options po ON po.id = l.po_id AND po.active
                WHERE l.id = %s AND l.leased_until <= now() AND l.retry_after <= now()
                FOR UPDATE OF l SKIP LOCKED
                """,
                [lease_id],
            )
            row = cursor.fetchone()
            if row is None or sorted(row[4]) != sorted(fm_ids):
                return None
            progress_id, resource_ids, po_id, period, _, attempts, last_error, pace = row
            # Membership again, now that the guards are held: a feature moved
            # to another collection since the first read would leave its new
            # collection unguarded, so try again later. Deletions are
            # confirmed: this read was on the primary, under the guards.
            members = _members(cursor, fm_ids)
            if not set(members.values()) <= set(guard.clean.collections):
                return None
            kept = sorted(fm_id for fm_id in fm_ids if fm_id in members)
            if not kept:
                cursor.execute("DELETE FROM extract_task_leases WHERE id = %s", [lease_id])
                return None

            if len(kept) == 1 and attempts >= settings.MAX_EXTRACT_TASK_ATTEMPTS:
                _fail_terminally(cursor, lease_id, dataset_id, resource_ids, po_id, period,
                                 progress_id, kept[0], attempts, last_error)
                return None

            token = uuid.uuid4()
            if len(kept) > 1 and attempts >= settings.EXTRACT_TASK_LEASE_BISECT_ATTEMPT:
                # Isolate whatever keeps failing: two children with fresh
                # budgets, one assigned now, the other due immediately.
                cut = len(kept) // 2
            elif len(kept) > _page_size(pace, len(resource_ids)):
                # The pair has proved slower than this page allowed for
                # (typically it timed out): cut it to size, without penalty.
                cut = _page_size(pace, len(resource_ids))
            else:
                cut = None
            if cut:
                assigned, queued = kept[:cut], kept[cut:]
                cursor.execute(
                    """
                    INSERT INTO extract_task_leases
                        (progress_id, dataset_id, resource_ids, po_id, task_group_period,
                         fm_ids, input_generations, token, leased_at, leased_until,
                         retry_after, created_at, attempts, last_error)
                    SELECT progress_id, dataset_id, resource_ids, po_id, task_group_period,
                           %s::int[], input_generations, gen_random_uuid(), now(), now(),
                           now(), created_at, 0, last_error
                    FROM extract_task_leases WHERE id = %s
                    """,
                    [queued, lease_id],
                )
                kept, attempts = assigned, 0
                metrics.LEASE_SPLITS.inc()

            generations = Generations(
                datasets=dict(guard.clean.datasets),
                collections={c: guard.clean.collections[c] for c in {members[f] for f in kept}},
            )
            cursor.execute(
                """
                UPDATE extract_task_leases SET
                    fm_ids = %s::int[], token = %s, leased_at = now(),
                    leased_until = now() + make_interval(secs => %s),
                    attempts = %s + 1, input_generations = %s::jsonb
                WHERE id = %s
                """,
                [kept, token, settings.EXTRACT_TASK_LEASE_SECONDS, attempts,
                 json.dumps(generations.as_json()), lease_id],
            )
    metrics.LEASE_TAKEOVERS.inc()
    return Lease(
        id=lease_id, token=token, progress_id=progress_id, dataset_id=dataset_id,
        resource_ids=list(resource_ids), po_id=po_id, task_group_period=period,
        fm_ids=kept, generations=generations, attempts=attempts + 1, takeover=True,
    )


def _fail_terminally(cursor, lease_id, dataset_id, resource_ids, po_id, period,
                     progress_id, fm_id, attempts, last_error):
    """A single feature that never completed: record it as an exhausted failure.

    The task row makes the failure visible to requests and monitoring. A
    request's own task for the feature wins the conflict and is untouched.
    """
    error = (last_error or f"lease abandoned after {attempts} assignments")[:100]
    cursor.execute(
        """
        INSERT INTO extract_tasks
            (dataset_id, resource_ids, task_group_period, fm_id, po_id, status,
             priority, attempts, submit_time, start_time, update_time,
             complete_time, error, kwargs, pair_id)
        VALUES (%s, %s::int[], %s, %s, %s, -1, 0, %s, now(), now(), now(), NULL, %s, NULL, %s)
        ON CONFLICT (dataset_id, po_id, resource_ids_hash, fm_id) WHERE kwargs IS NULL
        DO NOTHING
        """,
        [dataset_id, resource_ids, period, fm_id, po_id,
         settings.MAX_EXTRACT_TASK_ATTEMPTS, error, progress_id],
    )
    cursor.execute("DELETE FROM extract_task_leases WHERE id = %s", [lease_id])
    metrics.LEASE_PAGES.labels("exhausted").inc()
    logger.warning(
        "Lease %s: feature %s of pair %s failed %d assignments; recorded as a failed task",
        lease_id, fm_id, progress_id, attempts,
    )


# A current pair of an active, available dataset and an active option, due,
# untouched by a pending targeted reset, with cursor below its cap: the
# highest eligible feature id for a global dataset, or the coverage watermark
# for a non-global one (no watermark, no work).
_CANDIDATE_PAIRS_SQL = f"""
    SELECT p.id
    FROM extract_task_build_progress p
    JOIN datasets d ON d.id = p.dataset_id AND d.active
    JOIN processing_options po ON po.id = p.po_id AND po.active
    JOIN extract_input_state s
      ON s.kind = 'dataset' AND s.object_id = p.dataset_id AND NOT {UNAVAILABLE_SQL}
    LEFT JOIN extract_coverage_progress cp ON cp.dataset_id = p.dataset_id
    WHERE p.current AND p.retry_after <= now() AND {_PAIR_VALID}
      AND p.cursor_fm_id < CASE WHEN d.is_global THEN %(max_fm_id)s
                                ELSE LEAST(%(max_fm_id)s, COALESCE(cp.covered_up_to_fm_id, 0)) END
    ORDER BY p.priority DESC, p.id
    LIMIT 64
"""

_PAIR_SQL = """
    SELECT dataset_id, resource_ids, po_id, task_group_period
    FROM extract_task_build_progress WHERE id = %s
"""

_WINDOW_COLLECTIONS_SQL = """
    SELECT fm.fc_id, min(fm.id)
    FROM feat_map fm
    WHERE fm.id > %s AND fm.id <= %s
    GROUP BY fm.fc_id
"""

_COLLECTION_STATES_SQL = f"""
    SELECT object_id, epoch, {UNAVAILABLE_SQL}, rewind_from
    FROM extract_input_state
    WHERE kind = 'collection' AND object_id = ANY(%s::int[])
    ORDER BY object_id
    FOR SHARE SKIP LOCKED
"""

# The page: eligible features in the window with no task for this pair yet
# and not already in one of its outstanding leases (a rewind can bring the
# scan back over them). The task probe names every column of
# extract_tasks_pair_null_kwargs_idx so it seeks it; the full array is
# compared too, since the hash is only 32 bits; the ::int[] casts are needed
# because psycopg sends small int lists as int2[]; and the fm_id range is
# repeated inside the probe because the planner does not carry it across
# et.fm_id = fm.id, and without it misestimates a pair's freshly inserted
# rows (24-30 s against ~110 ms per scan, measured for the builder).
_PAGE_SQL = """
    SELECT fm.id, fm.fc_id
    FROM feat_map fm
    JOIN feature_collections fc ON fc.id = fm.fc_id
    WHERE fm.id > %(cursor)s AND fm.id <= %(end)s
      AND fm.fc_id = ANY(%(collections)s::int[])
      AND fc.active AND NOT fc.is_user_upload
      AND NOT EXISTS (SELECT 1 FROM extract_invalid_items i
                      WHERE i.item_kind = 'feature' AND i.item_id = fm.id)
      {coverage}
      AND NOT (fm.id = ANY(%(outstanding)s::int[]))
      AND NOT EXISTS (
          SELECT 1 FROM extract_tasks et
          WHERE et.dataset_id = %(dataset_id)s
            AND et.po_id = %(po_id)s
            AND et.resource_ids_hash = extract_tasks_resource_ids_hash(%(resource_ids)s::int[])
            AND et.fm_id = fm.id
            AND et.kwargs IS NULL
            AND et.resource_ids = %(resource_ids)s::int[]
            AND et.fm_id > %(cursor)s AND et.fm_id <= %(end)s)
    ORDER BY fm.id
    LIMIT %(page_size)s
"""

_COVERED = """
      AND EXISTS (
          SELECT 1 FROM coverage c
          WHERE c.geom_id = fm.geom_id AND c.dataset_id = %(dataset_id)s AND c.status = 1)
"""

# Same hash key, different array: a 32-bit collision with some other task.
_COLLISIONS_SQL = """
    SELECT et.fm_id FROM extract_tasks et
    WHERE et.dataset_id = %(dataset_id)s
      AND et.po_id = %(po_id)s
      AND et.resource_ids_hash = extract_tasks_resource_ids_hash(%(resource_ids)s::int[])
      AND et.fm_id = ANY(%(fm_ids)s::int[])
      AND et.kwargs IS NULL
      AND et.resource_ids <> %(resource_ids)s::int[]
    LIMIT 1
"""


def _lease_new_page():
    with connection.cursor() as cursor:
        cursor.execute("SELECT extract_eligible_max_fm_id()")
        max_fm_id = cursor.fetchone()[0]
        cursor.execute(_CANDIDATE_PAIRS_SQL, {"max_fm_id": max_fm_id})
        candidates = [r[0] for r in cursor.fetchall()]
    for pair_id in candidates:
        empty_windows = 0
        while empty_windows < 10:
            outcome = _scan_window(pair_id, max_fm_id)
            if isinstance(outcome, Lease):
                return outcome
            if outcome != "empty":
                break
            empty_windows += 1
    return None


def _scan_window(pair_id, max_fm_id):
    """Scan one window of a pair's cursor.

    Returns a Lease, "empty" (the cursor advanced past a window with nothing
    to lease), or "skip" (the pair is busy, blocked, finished or in error).
    """
    with connection.cursor() as cursor:
        cursor.execute(_PAIR_SQL, [pair_id])
        row = cursor.fetchone()
        if row is None:
            return "skip"
        dataset_id, resource_ids, po_id, period = row

    with transaction.atomic():
        with connection.cursor() as cursor:
            _timeouts(cursor)
            guard = lock_states([dataset_id], [], cursor=cursor)
            if not guard.all_clean:
                return "skip"
            # The pair first, then everything the scan depends on. A collection
            # publish locks every current pair before rewinding, so one this
            # transaction cannot see yet waits for our commit and then rewinds
            # the cursor we leave; one already committed is visible to the
            # reads below. Reading the watermark, the window's collections or
            # the dataset's coverage rule before this lock could pass a
            # feature whose rewind had already been applied. Collection states
            # are taken SKIP LOCKED after it, so the publish (which holds its
            # collection) never deadlocks us.
            cursor.execute(
                """
                SELECT p.cursor_fm_id, cp.covered_up_to_fm_id, d.is_global, p.seconds_per_feature
                FROM extract_task_build_progress p
                JOIN datasets d ON d.id = p.dataset_id
                LEFT JOIN extract_coverage_progress cp ON cp.dataset_id = p.dataset_id
                WHERE p.id = %s AND p.current AND p.retry_after <= now()
                FOR UPDATE OF p SKIP LOCKED
                """,
                [pair_id],
            )
            locked = cursor.fetchone()
            if locked is None:
                return "skip"
            cursor_fm_id, covered, is_global, pace = locked
            cap = max_fm_id if is_global else min(max_fm_id, covered or 0)
            if cursor_fm_id >= cap:
                return "skip"
            scan_end = min(cursor_fm_id + settings.EXTRACT_TASK_LEASE_SCAN_WINDOW, cap)
            cursor.execute(_WINDOW_COLLECTIONS_SQL, [cursor_fm_id, scan_end])
            window = sorted(cursor.fetchall(), key=lambda r: r[1])

            collections = sorted(fc_id for fc_id, _ in window)
            cursor.execute(_COLLECTION_STATES_SQL, [collections])
            states = {object_id: tuple(rest) for object_id, *rest in cursor.fetchall()}
            # Each collection's lowest feature in the window decides whether
            # the scan may pass it; see coverage.barrier_for.
            barrier = barrier_for([(min_id, fc_id) for fc_id, min_id in window], states)
            end = scan_end if barrier is None else min(scan_end, barrier - 1)
            if end <= cursor_fm_id:
                return "skip"
            clean = sorted(c for c, (_, unavailable, _) in states.items() if not unavailable)

            cursor.execute(
                """
                SELECT COALESCE(array_agg(f), '{}') FROM extract_task_leases l, unnest(l.fm_ids) AS f
                WHERE l.progress_id = %s AND f > %s AND f <= %s
                """,
                [pair_id, cursor_fm_id, end],
            )
            outstanding = cursor.fetchone()[0]
            params = {
                "cursor": cursor_fm_id, "end": end, "collections": clean,
                "outstanding": outstanding, "dataset_id": dataset_id, "po_id": po_id,
                "resource_ids": resource_ids,
                "page_size": _page_size(pace, len(resource_ids)),
            }
            cursor.execute(_PAGE_SQL.format(coverage="" if is_global else _COVERED), params)
            page = cursor.fetchall()
            fm_ids = [fm_id for fm_id, _ in page]

            if fm_ids:
                cursor.execute(_COLLISIONS_SQL, {**params, "fm_ids": fm_ids})
                collided = cursor.fetchone()
                if collided:
                    # Keep the work: neither lease nor advance past it.
                    error = (f"resource_ids hash collision at fm {collided[0]}: a task with the "
                             f"same hash and a different array exists")
                    cursor.execute(
                        """
                        UPDATE extract_task_build_progress
                        SET last_error = %s, retry_after = now() + make_interval(secs => %s)
                        WHERE id = %s
                        """,
                        [error[:200], PAIR_ERROR_BACKOFF_SECONDS, pair_id],
                    )
                    logger.error("Pair %s: %s", pair_id, error)
                    metrics.LEASE_ERRORS.labels("hash_collision").inc()
                    return "skip"

            full = len(fm_ids) == params["page_size"]
            new_cursor = fm_ids[-1] if full else end
            cursor.execute(
                "UPDATE extract_task_build_progress SET cursor_fm_id = %s, last_error = NULL WHERE id = %s",
                [new_cursor, pair_id],
            )
            if not fm_ids:
                return "empty"

            generations = Generations(
                datasets=dict(guard.clean.datasets),
                collections={fc_id: states[fc_id][0] for fc_id in {fc for _, fc in page}},
            )
            token = uuid.uuid4()
            cursor.execute(
                """
                INSERT INTO extract_task_leases
                    (progress_id, dataset_id, resource_ids, po_id, task_group_period,
                     fm_ids, input_generations, token, leased_at, leased_until,
                     retry_after, created_at, attempts)
                VALUES (%s, %s, %s::int[], %s, %s, %s::int[], %s::jsonb, %s, now(),
                        now() + make_interval(secs => %s), now(), now(), 1)
                RETURNING id
                """,
                [pair_id, dataset_id, resource_ids, po_id, period, fm_ids,
                 json.dumps(generations.as_json()), token, settings.EXTRACT_TASK_LEASE_SECONDS],
            )
            lease_id = cursor.fetchone()[0]
    return Lease(
        id=lease_id, token=token, progress_id=pair_id, dataset_id=dataset_id,
        resource_ids=list(resource_ids), po_id=po_id, task_group_period=period,
        fm_ids=fm_ids, generations=generations, attempts=1,
    )


# -- load ----------------------------------------------------------------------


@dataclass
class _Inputs:
    function: str
    short_name: str
    op_kwargs: dict
    paths: list[Path]  # position-aligned with lease.resource_ids
    setup_error: str | None = None


class _Reader:
    """Where a lease reads its inputs: the primary, or a caught-up standby.

    Standby reads are off by default (EXTRACT_TASK_LEASE_READ_REPLICA). When
    on, the claim's commit LSN is the barrier: the standby must have replayed
    it before anything is read there, so it already has every row the claim
    saw. Timeouts and recovery conflicts fall back to the primary.
    """

    def __init__(self):
        self.alias = "default"
        if not settings.EXTRACT_TASK_LEASE_READ_REPLICA or "replica" not in settings.DATABASES:
            return
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_current_wal_lsn()::text")
                lsn = cursor.fetchone()[0]
            if self._wait_for(lsn):
                self.alias = "replica"
            else:
                metrics.REPLICA_FALLBACKS.labels("lag").inc()
        except (OperationalError, InterfaceError):
            logger.warning("Standby barrier failed; reading from the primary", exc_info=True)
            metrics.REPLICA_FALLBACKS.labels("error").inc()
            connections["replica"].close()

    @staticmethod
    def _wait_for(lsn):
        deadline = time.monotonic() + settings.EXTRACT_TASK_LEASE_REPLICA_WAIT_SECONDS
        replica = connections["replica"]
        while True:
            # Autocommit: each poll is its own statement, holding no snapshot.
            with replica.cursor() as cursor:
                cursor.execute(
                    "SELECT NOT pg_is_in_recovery() OR pg_last_wal_replay_lsn() >= %s::pg_lsn",
                    [lsn],
                )
                if cursor.fetchone()[0]:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def fetch(self, sql, params):
        if self.alias != "default":
            try:
                with connections[self.alias].cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.fetchall()
            except (OperationalError, InterfaceError):
                # A recovery conflict cancels the standby query; the primary
                # always has the data.
                logger.warning("Standby read failed; using the primary", exc_info=True)
                metrics.REPLICA_FALLBACKS.labels("conflict").inc()
                connections[self.alias].close()
                self.alias = "default"
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()


def _load_inputs(lease, reader):
    """The option, ordered resources and category map, once per lease.

    A missing resource or option, or an unknown processor, is a setup error:
    every feature in the page becomes an explicit failed task rather than
    an endless retry.
    """
    rows = reader.fetch(
        """
        SELECT po.function, po.short_name, po.kwargs::text, d.path, d.mapped
        FROM processing_options po JOIN datasets d ON d.id = po.dataset_id
        WHERE po.id = %s AND d.id = %s
        """,
        [lease.po_id, lease.dataset_id],
    )
    if not rows and reader.alias != "default":
        reader.alias = "default"
        return _load_inputs(lease, reader)
    if not rows:
        return _Inputs("", "", {}, [], setup_error="processing option or dataset no longer exists")
    function, short_name, po_kwargs, dataset_path, mapped = rows[0]
    op_kwargs = _op_kwargs(short_name, json.loads(po_kwargs) if po_kwargs else None, None)

    resources = dict(reader.fetch(
        "SELECT id, path FROM dataset_resources WHERE id = ANY(%s::int[]) AND dataset_id = %s",
        [lease.resource_ids, lease.dataset_id],
    ))
    if len(resources) < len(set(lease.resource_ids)) and reader.alias != "default":
        reader.alias = "default"
        return _load_inputs(lease, reader)
    missing = [rid for rid in lease.resource_ids if rid not in resources]
    if missing:
        return _Inputs(function, short_name, op_kwargs, [],
                       setup_error=f"missing resources {missing[:5]}")
    try:
        get_func(function)
    except ValueError as exc:
        return _Inputs(function, short_name, op_kwargs, [], setup_error=str(exc))

    if mapped:
        op_kwargs["category_map"] = dict(reader.fetch(
            "SELECT map_val, map_name FROM mappings WHERE dataset_id = %s", [lease.dataset_id]
        ))
    paths = [Path(dataset_path) / resources[rid] for rid in lease.resource_ids]
    return _Inputs(function, short_name, op_kwargs, paths)


def _load_geometries(lease, reader, fm_ids):
    """WKB for one block, ``{fm_id: geometry}``.

    Already-leased features are loaded whatever their collection's activity:
    finishing them is harmless, and input generations still fence edits.
    Rows a standby lacks are read from the primary; a row the primary lacks
    was deleted, and the feature is dropped from the page.
    """
    sql = """
        SELECT fm.id, ST_AsBinary(g.shape)
        FROM feat_map fm JOIN features g ON g.id = fm.geom_id
        WHERE fm.id = ANY(%s::int[])
    """
    found = dict(reader.fetch(sql, [fm_ids]))
    missing = [f for f in fm_ids if f not in found]
    if missing and reader.alias != "default":
        with connection.cursor() as cursor:
            cursor.execute(sql, [missing])
            found.update(cursor.fetchall())
        metrics.REPLICA_FALLBACKS.labels("missing_rows").inc()
    return {fm_id: shapely.from_wkb(bytes(wkb)) for fm_id, wkb in found.items()}


# -- compute -------------------------------------------------------------------


@dataclass
class _FeatureOutcome:
    fm_id: int
    rows: list[tuple]  # _RESULT_COLUMNS order, task id placeholder
    status: int
    error: str | None


class _StopCheck:
    """Decides, between features, whether computation must stop.

    A graceful stop gives the page EXTRACT_WORKER_DRAIN_SECONDS from the
    moment it is first noticed; the lease's own expiry, less a margin, bounds
    it regardless.
    """

    def __init__(self, lease, stop_event):
        self.lease = lease
        self.stop_event = stop_event
        self.drain_deadline = None

    def __call__(self):
        now = time.monotonic()
        if now >= self.lease.deadline:
            raise AbandonPage("lease duration exceeded", refund=False)
        if self.stop_event is not None and self.stop_event.is_set():
            if self.drain_deadline is None:
                self.drain_deadline = now + settings.EXTRACT_WORKER_DRAIN_SECONDS
            elif now >= self.drain_deadline:
                raise AbandonPage("worker stopping", refund=True)


def _compute(lease, inputs, reader, check_stop):
    """Run every resource over every feature, a geometry block at a time.

    Block-major, resource-minor: a block's geometries are loaded once and
    each resource is opened once per block (batch processors) or called per
    feature. A feature/resource exception leaves that position NULL and
    makes the feature a failed task, exactly as on the task-row path.
    """
    if inputs.setup_error:
        return [
            _FeatureOutcome(fm_id, [], -1, f"setup: {inputs.setup_error}"[:100])
            for fm_id in lease.fm_ids
        ]
    func = get_func(inputs.function)
    batch = get_batch_func(inputs.function)
    n = len(lease.resource_ids)
    block_size = settings.EXTRACT_TASK_LEASE_BLOCK_SIZE
    outcomes = []
    for start in range(0, len(lease.fm_ids), block_size):
        check_stop()
        block_ids = lease.fm_ids[start:start + block_size]
        geometries = _load_geometries(lease, reader, block_ids)
        block = [fm_id for fm_id in block_ids if fm_id in geometries]
        produced = {fm_id: {} for fm_id in block}
        failures = {fm_id: [] for fm_id in block}
        for position, path in enumerate(inputs.paths):
            resource_id = lease.resource_ids[position]
            results = _run_resource(func, batch, [geometries[f] for f in block], path,
                                    dict(inputs.op_kwargs), check_stop)
            for index, result in results:
                fm_id = block[index]
                if isinstance(result, BaseException):
                    failures[fm_id].append((resource_id, position, result))
                    continue
                for name, value in result:
                    produced[fm_id].setdefault(name, {})[position] = value
        for fm_id in block:
            rows = _result_rows(produced[fm_id], n, prefix=(None, lease.dataset_id),
                                label=f"Lease {lease.id} fm {fm_id}")
            error = _failure_summary(failures[fm_id])
            outcomes.append(_FeatureOutcome(fm_id, rows, -1 if error else 1, error))
    return outcomes


def _run_resource(func, batch, geometries, path, op_kwargs, check_stop):
    """Yield ``(index, result_or_exception)`` for one resource over a block."""
    with catch_warnings(record=True) as warnings:
        if batch is not None:
            iterator = batch(geometries, path, **op_kwargs)
            try:
                for index, result in iterator:
                    yield index, result
                    check_stop()
            finally:
                iterator.close()
        else:
            for index, geometry in enumerate(geometries):
                try:
                    result = func(geometry, path, **dict(op_kwargs))
                except Exception as exc:
                    result = exc
                yield index, result
                check_stop()
        for w in warnings:
            logger.warning("Warning processing %s: %s", path, w.message)


# -- complete ------------------------------------------------------------------


_INSERT_TASKS_SQL = """
    INSERT INTO extract_tasks
        (dataset_id, resource_ids, task_group_period, fm_id, po_id, status,
         priority, attempts, submit_time, start_time, update_time,
         complete_time, error, kwargs, pair_id)
    SELECT %(dataset_id)s, %(resource_ids)s::int[], %(period)s, v.fm_id, %(po_id)s,
           v.status, 0, 0, %(leased_at)s, %(leased_at)s, now(),
           CASE WHEN v.status = 1 THEN now() END, v.error, NULL, %(pair_id)s
    FROM unnest(%(fm_ids)s::int[], %(statuses)s::int[], %(errors)s::text[])
        AS v(fm_id, status, error)
    ORDER BY v.fm_id
    ON CONFLICT (dataset_id, po_id, resource_ids_hash, fm_id) WHERE kwargs IS NULL
    DO NOTHING
    RETURNING id, fm_id
"""


def _check_lease(cursor, lease):
    """Lock the lease and decide whether this worker may still finish it.

    Returns None to proceed, or the outcome to report. Never writes to a
    lease whose token has changed.
    """
    cursor.execute(
        """
        SELECT l.token, p.current, d.active AND po.active
        FROM extract_task_leases l
        JOIN extract_task_build_progress p ON p.id = l.progress_id
        JOIN datasets d ON d.id = l.dataset_id
        JOIN processing_options po ON po.id = l.po_id
        WHERE l.id = %s
        FOR UPDATE OF l
        """,
        [lease.id],
    )
    row = cursor.fetchone()
    if row is None:
        return "missing"
    token, current, active = row
    if token != lease.token:
        return "stale"
    if not current:
        return "stale"
    if not active:
        _expire(cursor, lease, refund=True, error="parked: dataset or option inactive")
        return "parked"
    return None


def _expire(cursor, lease, *, refund, error=None, delay_seconds=0):
    """Give the page back: new token, due now (or after a delay)."""
    cursor.execute(
        """
        UPDATE extract_task_leases SET
            token = gen_random_uuid(), leased_until = now(),
            retry_after = now() + make_interval(secs => %s),
            attempts = GREATEST(attempts - %s, 0),
            last_error = COALESCE(%s, last_error)
        WHERE id = %s AND token = %s
        """,
        [delay_seconds, 1 if refund else 0, error[:100] if error else None, lease.id, lease.token],
    )
    return cursor.rowcount


def _insert_tasks(cursor, lease, outcomes):
    """INSERT the page's terminal tasks; ``{fm_id: task_id}`` for those inserted."""
    cursor.execute(
        _INSERT_TASKS_SQL,
        {
            "dataset_id": lease.dataset_id, "resource_ids": lease.resource_ids,
            "period": lease.task_group_period, "po_id": lease.po_id,
            "pair_id": lease.progress_id, "leased_at": _leased_at(cursor, lease),
            "fm_ids": [o.fm_id for o in outcomes],
            "statuses": [o.status for o in outcomes],
            "errors": [o.error for o in outcomes],
        },
    )
    inserted = {fm_id: task_id for task_id, fm_id in cursor.fetchall()}
    conflicted = [o.fm_id for o in outcomes if o.fm_id not in inserted]
    if conflicted:
        # A request's task (same array) wins and keeps its own results. A
        # different array under the same hash is not "already done".
        cursor.execute(
            _COLLISIONS_SQL,
            {"dataset_id": lease.dataset_id, "po_id": lease.po_id,
             "resource_ids": lease.resource_ids, "fm_ids": conflicted},
        )
        if cursor.fetchone():
            raise _PairCollision(conflicted)
    return inserted


def _leased_at(cursor, lease):
    cursor.execute("SELECT leased_at FROM extract_task_leases WHERE id = %s", [lease.id])
    return cursor.fetchone()[0]


def _copy_rows(cursor, outcomes, inserted):
    with connection.wrap_database_errors, cursor.copy(_COPY_RESULTS) as copy:
        for outcome in outcomes:
            task_id = inserted.get(outcome.fm_id)
            if task_id is None:
                continue
            for row in outcome.rows:
                copy.write_row((task_id,) + row[1:])


def _complete_once(lease, outcomes):
    guarded = time.perf_counter()
    with transaction.atomic():
        with connection.cursor() as cursor:
            _timeouts(cursor)
            transaction.on_commit(
                lambda: metrics.GUARD_SECONDS.labels("hold").observe(time.perf_counter() - guarded)
            )
            if not recheck(lease.generations, cursor=cursor):
                # Inputs changed: sync will re-token this lease when it
                # publishes; until then give the page back unpenalized.
                _expire(cursor, lease, refund=True)
                return "deferred"
            verdict = _check_lease(cursor, lease)
            if verdict is not None:
                return verdict
            inserted = _insert_tasks(cursor, lease, outcomes)
            _copy_rows(cursor, outcomes, inserted)
            cursor.execute(
                "DELETE FROM extract_task_leases WHERE id = %s AND token = %s",
                [lease.id, lease.token],
            )
            _record_features(lease, outcomes, inserted)
            return "completed"


def _complete_with_savepoints(lease, outcomes):
    """Store what can be stored, one feature per savepoint.

    Only after the bulk attempt failed on a value the database cannot store.
    Ownership is checked again: it may have changed between the two
    transactions. A feature whose rows cannot be stored becomes a failed task
    with no rows; its neighbours, the failures and the lease deletion still
    commit together. Any other error aborts the whole fallback, leaving the
    lease recoverable.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            _timeouts(cursor)
            if not recheck(lease.generations, cursor=cursor):
                _expire(cursor, lease, refund=True)
                return "deferred"
            verdict = _check_lease(cursor, lease)
            if verdict is not None:
                return verdict
            inserted_all = {}
            for outcome in sorted(outcomes, key=lambda o: o.fm_id):
                try:
                    with transaction.atomic():
                        inserted = _insert_tasks(cursor, lease, [outcome])
                        _copy_rows(cursor, [outcome], inserted)
                except DataError as exc:
                    if not _is_storage_error(exc):
                        raise
                    logger.warning(
                        "Lease %s: results for feature %s cannot be stored: %r",
                        lease.id, outcome.fm_id, exc,
                    )
                    failed = _FeatureOutcome(outcome.fm_id, [], -1, repr(exc)[:100])
                    with transaction.atomic():
                        inserted = _insert_tasks(cursor, lease, [failed])
                inserted_all.update(inserted)
            cursor.execute(
                "DELETE FROM extract_task_leases WHERE id = %s AND token = %s",
                [lease.id, lease.token],
            )
            _record_features(lease, outcomes, inserted_all)
            return "completed"


def _record_features(lease, outcomes, inserted):
    def committed():
        for outcome in outcomes:
            if outcome.fm_id not in inserted:
                label = "conflict"
            else:
                label = "completed" if outcome.status == 1 else "failed"
            metrics.LEASE_FEATURES.labels(str(lease.dataset_id), label).inc()

    transaction.on_commit(committed)


def _is_storage_error(exc):
    """A value-level failure: one of STORAGE_SQLSTATES, or a client dump error.

    psycopg raises DataError without a SQLSTATE when it cannot dump a Python
    value for COPY (a NUL in a string, an int beyond bigint); those are the
    same failure caught one step earlier.
    """
    cause = exc.__cause__
    sqlstate = getattr(cause, "sqlstate", None)
    return sqlstate in STORAGE_SQLSTATES or sqlstate is None


def complete_lease(lease, outcomes):
    """Commit a computed page, retrying transient failures from memory.

    Synchronous commit: a lost completion would leave a deleted lease's work
    neither in a task row nor in a lease. Retries rerun the whole transaction,
    including the token check, so a lost commit response is harmless: if the
    lease is already gone, the page committed (or was cancelled) and nothing
    more is written.
    """
    started = time.perf_counter()
    try:
        for attempt in range(3):
            try:
                outcome = _complete_once(lease, outcomes)
                break
            except (OperationalError, InterfaceError):
                if attempt == 2:
                    raise
                logger.warning("Retrying completion of lease %s", lease.id, exc_info=True)
                if not connection.in_atomic_block:
                    connection.close()
                time.sleep(0.25 * 2 ** attempt)
            except DataError as exc:
                if not _is_storage_error(exc):
                    raise
                outcome = _complete_with_savepoints(lease, outcomes)
                break
            except _PairCollision as exc:
                _back_off_collision(lease, exc.args[0])
                outcome = "collision"
                break
    finally:
        metrics.LEASE_PHASE_SECONDS.labels("commit").observe(time.perf_counter() - started)
    if outcome == "missing":
        # Committed by an earlier attempt whose response was lost, or
        # cancelled by sync. Either way there is nothing left to write.
        outcome = "gone"
    return outcome


def _back_off_collision(lease, fm_ids):
    """Keep the lease and its work; stop the pair until someone looks."""
    error = f"resource_ids hash collision completing lease {lease.id} (fm {fm_ids[:3]})"
    logger.error("Pair %s: %s", lease.progress_id, error)
    metrics.LEASE_ERRORS.labels("hash_collision").inc()
    with transaction.atomic():
        with connection.cursor() as cursor:
            _timeouts(cursor)
            cursor.execute(
                """
                UPDATE extract_task_build_progress
                SET last_error = %s, retry_after = now() + make_interval(secs => %s)
                WHERE id = %s
                """,
                [error[:200], PAIR_ERROR_BACKOFF_SECONDS, lease.progress_id],
            )
            cursor.execute("SELECT 1 FROM extract_task_leases WHERE id = %s FOR UPDATE", [lease.id])
            _expire(cursor, lease, refund=True, error="hash collision",
                    delay_seconds=PAIR_ERROR_BACKOFF_SECONDS)


def return_lease(lease, *, refund, error=None, delay_seconds=0):
    """Give back a page this worker will not finish, if it still owns it."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            _timeouts(cursor)
            cursor.execute("SELECT 1 FROM extract_task_leases WHERE id = %s FOR UPDATE", [lease.id])
            return _expire(cursor, lease, refund=refund, error=error, delay_seconds=delay_seconds)


# -- the whole page --------------------------------------------------------------


class InfrastructureError(Exception):
    """The database or standby failed; the page was given back unpenalized."""


def run_lease(lease, stop_event=None):
    """Load, compute and complete one leased page. Returns the outcome label.

    Raises InfrastructureError when the database failed, after returning the
    lease, so the caller can back off; every other failure is resolved here.
    """
    check_stop = _StopCheck(lease, stop_event)
    logger.info(
        "Lease %s: pair %s, %d features%s", lease.id, lease.progress_id, len(lease.fm_ids),
        " (takeover)" if lease.takeover else "",
    )
    try:
        started = time.perf_counter()
        reader = _Reader()
        inputs = _load_inputs(lease, reader)
        metrics.LEASE_PHASE_SECONDS.labels("load").observe(time.perf_counter() - started)
        started = time.perf_counter()
        outcomes = _compute(lease, inputs, reader, check_stop)
        computed = time.perf_counter() - started
        metrics.LEASE_PHASE_SECONDS.labels("compute").observe(computed)
    except AbandonPage as exc:
        logger.warning("Lease %s abandoned: %s", lease.id, exc.reason)
        _safe_return(lease, refund=exc.refund, error=exc.reason)
        outcome = "returned" if exc.refund else "timed_out"
        if not exc.refund:
            # It ran out of time, so each feature takes at least this long;
            # the takeover cuts the page to the size that implies.
            _record_pace(lease, (time.monotonic() - lease.assigned_at) / len(lease.fm_ids),
                         at_least=True)
        metrics.LEASE_PAGES.labels(outcome).inc()
        return outcome
    except (OperationalError, InterfaceError) as exc:
        metrics.LEASE_ERRORS.labels("database").inc()
        _safe_return(lease, refund=True, error=f"database: {exc!r}")
        raise InfrastructureError(str(exc)) from exc
    except Exception as exc:
        # Unexpected and possibly repeatable: the assignment counts, so a
        # page that always does this is split and then isolated.
        logger.exception("Lease %s failed", lease.id)
        metrics.LEASE_ERRORS.labels(type(exc).__name__[:40]).inc()
        delay = min(300, 15 * 2 ** max(lease.attempts - 1, 0)) * random.uniform(0.75, 1.25)
        _safe_return(lease, refund=False, error=repr(exc), delay_seconds=delay)
        metrics.LEASE_PAGES.labels("failed").inc()
        return "failed"

    try:
        outcome = complete_lease(lease, outcomes)
    except (OperationalError, InterfaceError) as exc:
        metrics.LEASE_ERRORS.labels("database").inc()
        _safe_return(lease, refund=True, error=f"database: {exc!r}")
        raise InfrastructureError(str(exc)) from exc
    except (DataError, IntegrityError) as exc:
        logger.exception("Lease %s could not be stored", lease.id)
        metrics.LEASE_ERRORS.labels(type(exc).__name__).inc()
        _safe_return(lease, refund=False, error=repr(exc))
        outcome = "failed"
    if outcome == "completed":
        _record_pace(lease, computed / len(lease.fm_ids))
    metrics.LEASE_PAGES.labels(outcome).inc()
    logger.info("Lease %s: %s", lease.id, outcome)
    return outcome


def _safe_return(lease, **kwargs):
    try:
        return_lease(lease, **kwargs)
    except Exception:
        # Expiry recovers it.
        logger.exception("Could not return lease %s; it will expire", lease.id)


def lease_health():
    """Outstanding-lease health, for metrics and the status command."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE l.leased_until <= now()),
                   count(*) FILTER (WHERE NOT (d.active AND po.active)),
                   COALESCE(EXTRACT(EPOCH FROM now() - min(l.created_at)), 0),
                   COALESCE(max(l.attempts), 0),
                   COALESCE(sum(cardinality(l.fm_ids)), 0)
            FROM extract_task_leases l
            JOIN datasets d ON d.id = l.dataset_id
            JOIN processing_options po ON po.id = l.po_id
            """
        )
        total, expired, parked, oldest, max_attempts, features = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM extract_task_build_progress WHERE current AND last_error IS NOT NULL"
        )
        pair_errors = cursor.fetchone()[0]
    return {
        "outstanding": total, "expired": expired, "parked": parked,
        "oldest_seconds": float(oldest), "max_attempts": max_attempts,
        "features": int(features), "pair_errors": pair_errors,
    }
