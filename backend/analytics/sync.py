"""Reconcile dirty input scopes: pairs, resets, rewinds, then publish.

extract_input_state is a durable queue of input changes (see
analytics.changes). sync_extract_work, run by beat every
EXTRACT_SYNC_INTERVAL_SECONDS and woken early by ingest, works through it.

Each transaction locks one dirty scope, performs one bounded phase or chunk,
saves a checkpoint and commits, so no transaction is long and a crash loses at
most one chunk. Concurrent syncs skip scopes another one holds. A scope is
only marked clean (applied_generation = generation) by its final publish
transaction, after every phase its flags call for has finished for that exact
generation; a change between chunks invalidates the checkpoint and the phases
restart with the flags accumulated so far.

Dataset scope phases:

    pairs           retire displaced sets, insert or reactivate current ones
    reset_tasks     reset every task in the partition, chunk by chunk
    reset_items     reset the tasks of the logged resources and options
    reset_coverage  delete the dataset's coverage, chunk by chunk
    publish         rewind cursors and coverage, re-token leases, mark clean

Collection scope phases:

    reset_items     reset the logged features' tasks in each partition
    reset_coverage  delete coverage for the collection's geometries (only
                    invalidate_extract_inputs sets it, with a rewind to 0)
    publish         rewind every dataset's cursors and coverage below the
                    change, re-token leases that touch it, mark clean

A reset deletes background tasks (those no request links) with their
results, and returns request-linked ones to pending. The publish rewinds
every affected cursor below the deleted features, so leases bring them back;
pending rows are only ever a request's.

Bootstrap-pending datasets are left to initialize_extract_work, which uses
the same pair reconciliation and then hands the scope back to ordinary sync.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from django.conf import settings
from django.db import OperationalError, connection, transaction

from analytics.background_metrics import record_work
from analytics.changes import COLLECTION, DATASET, jsonb
from analytics.models import ExtractInvalidItem

logger = logging.getLogger(__name__)

# Generous: chunks are bounded by row counts, this only stops a pathological
# plan from holding a pooler connection indefinitely.
STATEMENT_TIMEOUT_MS = 5 * 60 * 1000
LOCK_TIMEOUT_MS = 5 * 1000
# FeatMaps a collection reset examines per chunk, before the task chunk limit.
_FM_BATCH = 500
_LOCK_NOT_AVAILABLE = "55P03"
# Backoff for a scope whose phase raised: doubles per consecutive failure.
_BACKOFF_BASE_SECONDS = 30
_BACKOFF_MAX_SECONDS = 3600

_DATASET_PHASES = ("pairs", "reset_tasks", "reset_items", "reset_coverage", "publish")
_COLLECTION_PHASES = ("reset_items", "reset_coverage", "publish")


class SyncConfigError(Exception):
    """An input configuration sync cannot reconcile, shown on the scope.

    The scope stays dirty, with the message in last_error, until someone
    fixes the input; the fix is itself a change and clears the backoff.
    """


@dataclass
class _Scope:
    kind: str
    object_id: int
    generation: int
    rewind_from: int | None
    sync_pairs: bool
    reset_tasks: bool
    reset_coverage: bool
    checkpoint: dict
    items: bool = False

    def phases(self):
        wanted = {
            "pairs": self.sync_pairs,
            "reset_tasks": self.reset_tasks,
            "reset_items": self.items,
            "reset_coverage": self.reset_coverage,
            "publish": True,
        }
        order = _DATASET_PHASES if self.kind == DATASET else _COLLECTION_PHASES
        return [p for p in order if wanted[p]]

    def position(self):
        """``(phase, checkpoint)`` to resume from, restarting on a new generation."""
        cp = self.checkpoint or {}
        phases = self.phases()
        if cp.get("generation") == self.generation and cp.get("phase") in phases:
            return cp["phase"], cp
        return phases[0], {"generation": self.generation, "phase": phases[0]}


# -- entry point ---------------------------------------------------------------


_DUE_SCOPES_SQL = """
    SELECT kind, object_id FROM extract_input_state
    WHERE generation <> applied_generation
      AND NOT bootstrap_pending
      AND retry_after <= now()
    ORDER BY retry_after, updated_at, kind, object_id
    LIMIT %s
"""


def sync_extract_work(max_chunks=None):
    """Advance dirty scopes by up to ``max_chunks`` transactions.

    Round-robin across the due scopes, so one dataset's long reset cannot
    starve a collection whose single publish would unblock its leases. A scope
    whose phase raises is backed off and the rest continue.
    """
    if max_chunks is None:
        max_chunks = settings.EXTRACT_SYNC_CHUNKS_PER_RUN
    stats = {"chunks": 0, "published": 0, "errors": 0, "skipped": 0}
    with connection.cursor() as cursor:
        cursor.execute(_DUE_SCOPES_SQL, [max(max_chunks, 1) * 4])
        queue = list(cursor.fetchall())

    while queue and stats["chunks"] < max_chunks:
        kind, object_id = queue.pop(0)
        try:
            outcome = _run_chunk(kind, object_id)
        except Exception as exc:
            if isinstance(exc, OperationalError) and (
                getattr(exc.__cause__, "sqlstate", None) == _LOCK_NOT_AVAILABLE
            ):
                # Contention, not a fault: a claim or chunk held a row this
                # chunk needed past LOCK_TIMEOUT_MS. Try again next run,
                # without backoff.
                stats["skipped"] += 1
                continue
            stats["errors"] += 1
            logger.exception("Extract sync failed for %s %s", kind, object_id)
            _record_failure(kind, object_id, exc)
            record_work("sync_errors", 1)
            continue
        if outcome in ("locked", "clean", "deferred"):
            stats["skipped"] += 1
            continue
        stats["chunks"] += 1
        if outcome == "published":
            stats["published"] += 1
        else:
            queue.append((kind, object_id))
    return stats


def _set_timeouts(cursor):
    cursor.execute(
        "SET LOCAL statement_timeout = %s; SET LOCAL lock_timeout = %s",
        [STATEMENT_TIMEOUT_MS, LOCK_TIMEOUT_MS],
    )


_SCOPE_COLUMNS = (
    "generation, applied_generation, rewind_from, sync_pairs, reset_tasks, "
    "reset_coverage, bootstrap_pending, checkpoint, "
    "EXISTS (SELECT 1 FROM extract_invalid_items i "
    "WHERE i.scope_kind = extract_input_state.kind AND i.scope_id = extract_input_state.object_id)"
)


def _scope_from_row(kind, object_id, row):
    (generation, applied, rewind_from, sync_pairs, reset_tasks,
     reset_coverage, bootstrap_pending, checkpoint, items) = row
    if generation == applied or bootstrap_pending:
        return None
    return _Scope(
        kind, object_id, generation, rewind_from, sync_pairs, reset_tasks,
        reset_coverage, jsonb(checkpoint) or {}, items,
    )


def _peek(kind, object_id):
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {_SCOPE_COLUMNS} FROM extract_input_state WHERE kind = %s AND object_id = %s",
            [kind, object_id],
        )
        row = cursor.fetchone()
    return None if row is None else _scope_from_row(kind, object_id, row)


def _lock_scope(cursor, kind, object_id):
    cursor.execute(
        f"SELECT {_SCOPE_COLUMNS} FROM extract_input_state "
        "WHERE kind = %s AND object_id = %s FOR UPDATE SKIP LOCKED",
        [kind, object_id],
    )
    row = cursor.fetchone()
    return row


def _run_chunk(kind, object_id):
    """One transaction of work on one scope.

    Returns "locked" (another transaction holds it), "clean" (nothing to
    do), "deferred" (its partitions could not be created yet), "progress"
    or "published".
    """
    scope = _peek(kind, object_id)
    if scope is None:
        return "clean"
    if kind == DATASET and scope.position()[0] == "pairs" and not _partitions_ready(object_id):
        return "deferred"
    # A collection's publish needs no dataset state: it touches only pair,
    # watermark and lease rows, whose own row locks serialize it against a
    # dataset's sync, and its LEAST rewinds commute with theirs.
    with transaction.atomic():
        with connection.cursor() as cursor:
            _set_timeouts(cursor)
            row = _lock_scope(cursor, kind, object_id)
            if row is None:
                return "locked"
            scope = _scope_from_row(kind, object_id, row)
            if scope is None:
                return "clean"
            phase, checkpoint = scope.position()

            if phase == "publish":
                _publish(cursor, scope)
                record_work("sync_published", 1)
                return "published"

            done, checkpoint = _PHASES[(kind, phase)](cursor, scope, checkpoint)
            if done:
                phases = scope.phases()
                nxt = phases[phases.index(phase) + 1]
                checkpoint = {"generation": scope.generation, "phase": nxt}
            checkpoint["generation"] = scope.generation
            checkpoint.setdefault("phase", phase)
            _save_checkpoint(cursor, scope, checkpoint)
            record_work("sync_chunks", 1)
            return "progress"


def _save_checkpoint(cursor, scope, checkpoint):
    import json

    cursor.execute(
        """
        UPDATE extract_input_state
        SET checkpoint = %s::jsonb, updated_at = clock_timestamp()
        WHERE kind = %s AND object_id = %s AND generation = %s
        """,
        [json.dumps(checkpoint), scope.kind, scope.object_id, scope.generation],
    )


def _record_failure(kind, object_id, exc):
    """Back off a failed scope without losing its phase or a newer change."""
    import json

    message = f"{type(exc).__name__}: {exc}"[:2000]
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT generation, checkpoint FROM extract_input_state "
                    "WHERE kind = %s AND object_id = %s FOR UPDATE SKIP LOCKED",
                    [kind, object_id],
                )
                row = cursor.fetchone()
                if row is None:
                    return
                generation, checkpoint = row
                checkpoint = dict(jsonb(checkpoint) or {})
                failures = int(checkpoint.get("failures", 0)) + 1
                checkpoint["failures"] = failures
                delay = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * 2 ** (failures - 1))
                delay *= random.uniform(0.75, 1.25)
                cursor.execute(
                    """
                    UPDATE extract_input_state
                    SET last_error = %s, checkpoint = %s::jsonb,
                        retry_after = clock_timestamp() + make_interval(secs => %s)
                    WHERE kind = %s AND object_id = %s AND generation = %s
                    """,
                    [message, json.dumps(checkpoint), delay, kind, object_id, generation],
                )
    except Exception:
        logger.exception("Could not record sync failure for %s %s", kind, object_id)


# -- pairs ---------------------------------------------------------------------


def _partitions_ready(dataset_id):
    """Whether the dataset's pairs may be created: its partitions exist first.

    The first pairs phase is what lets workers write a dataset's rows, within
    a sync interval of it being created, so this is the last moment a missing
    partition is cheap to add (see datasets.partitions). Runs outside the
    scope's transaction: the DDL takes ACCESS EXCLUSIVE on extract_tasks, which
    must be held only for the CREATE, not for a whole chunk. A lock_timeout
    defers the scope to the next run. Rows already parked in DEFAULT make the
    CREATE impossible and cannot be fixed by waiting, so they do not hold the
    pairs back; ensure-dataset-partitions reports them.
    """
    from datasets.partitions import (
        ensure_dataset_partitions,
        missing_partitions,
        rows_parked_in_default,
    )

    if not missing_partitions(dataset_id):
        return True
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM datasets WHERE id = %s", [dataset_id])
        if cursor.fetchone() is None:
            return True
    if any(rows_parked_in_default(dataset_id).values()):
        return True
    ensure_dataset_partitions(dataset_id)
    return not missing_partitions(dataset_id)



_DATASET_SQL = "SELECT id, task_group_period FROM datasets WHERE id = %s"

_STANDARD_SETS_SQL = """
    SELECT ARRAY[r.id], NULL::date
    FROM dataset_resources r WHERE r.dataset_id = %s ORDER BY r.id
"""

_GROUPED_SETS_SQL = """
    SELECT array_agg(r.id ORDER BY r.id),
           (date_trunc(%s, r.temporal AT TIME ZONE 'UTC'))::date AS bucket
    FROM dataset_resources r
    WHERE r.dataset_id = %s
    GROUP BY bucket
    ORDER BY bucket
"""


def desired_sets(cursor, dataset_id):
    """``(period, [(resource_ids, bucket), ...])`` the dataset should have now.

    Every resource and every option counts, active or not: inactivity parks a
    pair, it does not remove it. A grouped resource with no temporal value
    has no bucket, which is a configuration error, not something to drop.
    """
    cursor.execute(_DATASET_SQL, [dataset_id])
    row = cursor.fetchone()
    if row is None:
        return None, []
    _, period = row
    if period is None:
        cursor.execute(_STANDARD_SETS_SQL, [dataset_id])
        return None, [(list(ids), bucket) for ids, bucket in cursor.fetchall()]
    cursor.execute(
        "SELECT id FROM dataset_resources WHERE dataset_id = %s AND temporal IS NULL ORDER BY id LIMIT 20",
        [dataset_id],
    )
    undated = [r[0] for r in cursor.fetchall()]
    if undated:
        raise SyncConfigError(
            f"dataset {dataset_id} groups by {period}, but resources {undated} have no temporal value"
        )
    cursor.execute(_GROUPED_SETS_SQL, [period, dataset_id])
    return period, [(list(ids), bucket) for ids, bucket in cursor.fetchall()]


_UPSERT_PAIR_SQL = """
    INSERT INTO extract_task_build_progress AS p
        (resource_ids, po_id, dataset_id, bucket, task_group_period, current,
         priority, cursor_fm_id, retry_after)
    VALUES (%s::int[], %s, %s, %s, %s, true, 0, 0, now())
    ON CONFLICT (resource_ids, po_id) DO UPDATE SET
        current = true,
        cursor_fm_id = CASE WHEN p.current THEN p.cursor_fm_id ELSE 0 END,
        last_error = CASE WHEN p.current THEN p.last_error ELSE NULL END,
        retry_after = CASE WHEN p.current THEN p.retry_after ELSE now() END,
        dataset_id = EXCLUDED.dataset_id,
        bucket = EXCLUDED.bucket,
        task_group_period = EXCLUDED.task_group_period
    WHERE NOT p.current
       OR (p.dataset_id, p.bucket, p.task_group_period)
          IS DISTINCT FROM (EXCLUDED.dataset_id, EXCLUDED.bucket, EXCLUDED.task_group_period)
"""


def reconcile_pairs(cursor, dataset_id):
    """Make the dataset's current pairs exactly its desired sets.

    Caller holds the dataset's state exclusively. Arrays are never rewritten:
    a changed bucket retires its old set and selects (inserts or reactivates)
    the new one, so A -> B -> C needs three rows and A -> B -> A reuses the
    first, cursor restarted. Displaced sets are retired before any insert, so
    the one-current-pair-per-bucket index never sees two. Retiring deletes
    the pair's leases: that work is obsolete, not abandoned.

    Returns ``(retired, selected)`` counts.
    """
    period, sets = desired_sets(cursor, dataset_id)
    cursor.execute("SELECT id FROM processing_options WHERE dataset_id = %s ORDER BY id", [dataset_id])
    po_ids = [r[0] for r in cursor.fetchall()]
    desired = {(tuple(ids), po_id): bucket for ids, bucket in sets for po_id in po_ids}

    cursor.execute(
        """
        SELECT id, resource_ids, po_id FROM extract_task_build_progress
        WHERE dataset_id = %s AND current ORDER BY id FOR UPDATE
        """,
        [dataset_id],
    )
    displaced = [pid for pid, ids, po_id in cursor.fetchall() if (tuple(ids), po_id) not in desired]
    if displaced:
        cursor.execute(
            """
            DELETE FROM extract_task_leases WHERE id IN (
                SELECT id FROM extract_task_leases WHERE progress_id = ANY(%s)
                ORDER BY id FOR UPDATE)
            """,
            [displaced],
        )
        cursor.execute(
            "UPDATE extract_task_build_progress SET current = false WHERE id = ANY(%s)",
            [displaced],
        )

    selected = 0
    for (ids, po_id), bucket in sorted(desired.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        cursor.execute(_UPSERT_PAIR_SQL, [list(ids), po_id, dataset_id, bucket, period])
        selected += cursor.rowcount
    return len(displaced), selected


def _phase_pairs(cursor, scope, checkpoint):
    retired, selected = reconcile_pairs(cursor, scope.object_id)
    if retired or selected:
        logger.info(
            "Extract sync: dataset %s retired %d pairs, selected %d",
            scope.object_id, retired, selected,
        )
    return True, checkpoint


# -- task resets ---------------------------------------------------------------


# Background tasks (no request links them) are deleted with their results:
# they carry nothing a lease cannot recompute, and the publish rewinds their
# pairs below them. Request-linked tasks keep their ids, RequestMap links,
# arrays and priority, and return to pending with a fresh claim stamp, so a
# worker still holding one fails its fence. A task naming a resource that no
# longer exists cannot run again: it becomes a terminal failure with its
# retries exhausted, so a request waiting on it fails visibly.
_RESET_CHUNK_SQL = """
    WITH chunk AS (
        SELECT unnest(%(ids)s::bigint[]) AS id
    ),
    linked AS (
        SELECT DISTINCT rm.task_id AS id FROM request_map rm JOIN chunk ON chunk.id = rm.task_id
        WHERE rm.dataset_id = %(dataset_id)s
    ),
    dropped AS (
        DELETE FROM extract_data d USING chunk
        WHERE d.dataset_id = %(dataset_id)s AND d.extract_task_id = chunk.id
          AND d.dataset_id = ANY(%(datasets)s::int[])
    ),
    background AS (
        DELETE FROM extract_tasks t USING chunk
        WHERE t.dataset_id = %(dataset_id)s AND t.id = chunk.id
          AND t.dataset_id = ANY(%(datasets)s::int[])
          AND t.id NOT IN (SELECT id FROM linked)
    )
    UPDATE extract_tasks AS t SET
        status = CASE WHEN t.resource_ids <@ %(resources)s::int[] THEN 0 ELSE -1 END,
        attempts = CASE WHEN t.resource_ids <@ %(resources)s::int[] THEN 0 ELSE %(max_attempts)s END,
        error = CASE WHEN t.resource_ids <@ %(resources)s::int[] THEN NULL
                     ELSE 'input deleted: a resource of this task no longer exists' END,
        start_time = NULL,
        complete_time = NULL,
        update_time = clock_timestamp()
    FROM linked
    WHERE t.dataset_id = %(dataset_id)s AND t.id = linked.id
      AND t.dataset_id = ANY(%(datasets)s::int[])
"""


def _reset_tasks(cursor, dataset_id, task_ids):
    if not task_ids:
        return 0
    cursor.execute("SELECT id FROM dataset_resources WHERE dataset_id = %s", [dataset_id])
    resources = [r[0] for r in cursor.fetchall()]
    cursor.execute(
        _RESET_CHUNK_SQL,
        {
            "ids": sorted(task_ids),
            "dataset_id": dataset_id,
            "datasets": [dataset_id],
            "resources": resources,
            "max_attempts": settings.MAX_EXTRACT_TASK_ATTEMPTS,
        },
    )
    record_work("tasks_reset", len(task_ids))
    return len(task_ids)


def _phase_dataset_reset_tasks(cursor, scope, checkpoint):
    """Reset the next chunk of the dataset's partition, all kwargs and statuses."""
    limit = settings.EXTRACT_RESET_CHUNK_SIZE
    fm_id, task_id = checkpoint.get("fm_id", 0), checkpoint.get("task_id", 0)
    cursor.execute(
        """
        SELECT fm_id, id FROM extract_tasks
        WHERE dataset_id = %s AND (fm_id, id) > (%s, %s)
        ORDER BY fm_id, id LIMIT %s
        """,
        [scope.object_id, fm_id, task_id, limit],
    )
    rows = cursor.fetchall()
    _reset_tasks(cursor, scope.object_id, [tid for _, tid in rows])
    if len(rows) < limit:
        return True, checkpoint
    checkpoint.update(fm_id=rows[-1][0], task_id=rows[-1][1])
    return False, checkpoint


def _items(cursor, scope, item_kind):
    cursor.execute(
        """
        SELECT item_id FROM extract_invalid_items
        WHERE scope_kind = %s AND scope_id = %s AND item_kind = %s ORDER BY item_id
        """,
        [scope.kind, scope.object_id, item_kind],
    )
    return [r[0] for r in cursor.fetchall()]


# Every (option, resource set) whose tasks a logged option or resource
# invalidates: the pairs that name it, current or retired, and the
# single-resource sets requests use.
_ITEM_SETS_SQL = """
    SELECT po_id, resource_ids FROM extract_task_build_progress
    WHERE dataset_id = %(dataset_id)s
      AND (po_id = ANY(%(options)s::int[]) OR resource_ids && %(resources)s::int[])
    UNION
    SELECT po.id, ARRAY[r.r] FROM processing_options po
    CROSS JOIN unnest(%(resources)s::int[]) AS r(r)
    WHERE po.dataset_id = %(dataset_id)s
    UNION
    SELECT po.id, ARRAY[r.id] FROM processing_options po
    JOIN dataset_resources r ON r.dataset_id = po.dataset_id
    WHERE po.dataset_id = %(dataset_id)s AND po.id = ANY(%(options)s::int[])
    ORDER BY 1, 2
"""

# One set's tasks, in feature order, by range on
# extract_tasks_pair_null_kwargs_idx (dataset_id, po_id, hash, fm_id).
_SET_TASKS_SQL = """
    SELECT fm_id, id FROM extract_tasks
    WHERE dataset_id = %(dataset_id)s AND po_id = %(po_id)s
      AND resource_ids_hash = extract_tasks_resource_ids_hash(%(set)s::int[])
      AND resource_ids = %(set)s::int[] AND kwargs IS NULL
      AND fm_id > %(after)s
    ORDER BY fm_id LIMIT %(limit)s
"""

# Custom-kwargs tasks (requests only) through their small partial index.
_KWARGS_TASKS_SQL = """
    SELECT id FROM extract_tasks
    WHERE dataset_id = %(dataset_id)s AND kwargs IS NOT NULL AND id > %(after)s
      AND (po_id = ANY(%(options)s::int[]) OR resource_ids && %(resources)s::int[])
    ORDER BY id LIMIT %(limit)s
"""


def _phase_dataset_reset_items(cursor, scope, checkpoint):
    """Reset the next chunk of the tasks the logged options and resources name.

    Set by set, each by index range, then the custom-kwargs tasks: the work
    is proportional to the tasks affected, not to the partition.
    """
    params = {
        "dataset_id": scope.object_id,
        "options": _items(cursor, scope, ExtractInvalidItem.OPTION),
        "resources": _items(cursor, scope, ExtractInvalidItem.RESOURCE),
        "limit": settings.EXTRACT_RESET_CHUNK_SIZE,
    }
    cursor.execute(_ITEM_SETS_SQL, params)
    sets = cursor.fetchall()
    position = checkpoint.get("set", 0)
    if position < len(sets):
        po_id, resource_ids = sets[position]
        cursor.execute(_SET_TASKS_SQL, {
            **params, "po_id": po_id, "set": resource_ids, "after": checkpoint.get("fm_id", 0),
        })
        rows = cursor.fetchall()
        _reset_tasks(cursor, scope.object_id, [tid for _, tid in rows])
        if len(rows) == params["limit"]:
            checkpoint["fm_id"] = rows[-1][0]
        else:
            checkpoint.update(set=position + 1, fm_id=0)
        return False, checkpoint
    cursor.execute(_KWARGS_TASKS_SQL, {**params, "after": checkpoint.get("task_id", 0)})
    ids = [r[0] for r in cursor.fetchall()]
    _reset_tasks(cursor, scope.object_id, ids)
    if len(ids) < params["limit"]:
        return True, checkpoint
    checkpoint["task_id"] = ids[-1]
    return False, checkpoint


def _phase_collection_reset_items(cursor, scope, checkpoint):
    """Reset the next chunk of the logged features' tasks, one partition at a time."""
    limit = settings.EXTRACT_RESET_CHUNK_SIZE
    dataset_id = checkpoint.get("dataset_id")
    if dataset_id is None:
        dataset_id = _next_dataset(cursor, 0)
        checkpoint.update(dataset_id=dataset_id, fm_id=0, task_id=0)
    while dataset_id is not None:
        fm_id, task_id = checkpoint.get("fm_id", 0), checkpoint.get("task_id", 0)
        cursor.execute(
            """
            SELECT item_id FROM extract_invalid_items
            WHERE scope_kind = %s AND scope_id = %s AND item_kind = %s AND item_id >= %s
            ORDER BY item_id LIMIT %s
            """,
            [scope.kind, scope.object_id, ExtractInvalidItem.FEATURE, fm_id, _FM_BATCH],
        )
        fms = [r[0] for r in cursor.fetchall()]
        if not fms:
            dataset_id = _next_dataset(cursor, dataset_id)
            checkpoint.update(dataset_id=dataset_id, fm_id=0, task_id=0)
            continue
        cursor.execute(
            """
            SELECT fm_id, id FROM extract_tasks
            WHERE dataset_id = %s AND fm_id = ANY(%s::int[]) AND (fm_id, id) > (%s, %s)
            ORDER BY fm_id, id LIMIT %s
            """,
            [dataset_id, fms, fm_id, task_id, limit],
        )
        rows = cursor.fetchall()
        _reset_tasks(cursor, dataset_id, [tid for _, tid in rows])
        if len(rows) == limit:
            checkpoint.update(fm_id=rows[-1][0], task_id=rows[-1][1])
        elif len(fms) == _FM_BATCH:
            checkpoint.update(fm_id=fms[-1] + 1, task_id=0)
        else:
            dataset_id = _next_dataset(cursor, dataset_id)
            checkpoint.update(dataset_id=dataset_id, fm_id=0, task_id=0)
        if dataset_id is None:
            break
        # One partition and one bounded chunk per transaction.
        return False, checkpoint
    return True, checkpoint


def _next_dataset(cursor, after):
    cursor.execute("SELECT min(id) FROM datasets WHERE id > %s", [after])
    return cursor.fetchone()[0]


# -- coverage resets -----------------------------------------------------------


def _phase_dataset_reset_coverage(cursor, scope, checkpoint):
    """Delete the next chunk of the dataset's coverage rows.

    coverage is keyed (geom_id, dataset_id); walking geom_id order through
    that index bounds each chunk without a dataset index.
    """
    limit = settings.EXTRACT_COVERAGE_CHUNK_SIZE
    after = checkpoint.get("fm_id", 0)
    cursor.execute(
        """
        WITH doomed AS (
            SELECT geom_id FROM coverage
            WHERE dataset_id = %s AND geom_id > %s
            ORDER BY geom_id LIMIT %s
        )
        DELETE FROM coverage c USING doomed
        WHERE c.dataset_id = %s AND c.geom_id = doomed.geom_id
        RETURNING c.geom_id
        """,
        [scope.object_id, after, limit, scope.object_id],
    )
    geoms = [r[0] for r in cursor.fetchall()]
    if len(geoms) < limit:
        return True, checkpoint
    checkpoint["fm_id"] = max(geoms)
    return False, checkpoint


def _phase_collection_reset_coverage(cursor, scope, checkpoint):
    """Delete coverage, for every dataset, of the next chunk of the collection's geometries.

    Only invalidate_extract_inputs asks for this, and it rewinds to 0, which
    brings back every feature whose geometry lost coverage here, shared ones
    included. A shape edit deletes just its geometry's coverage in its trigger.
    """
    limit = settings.EXTRACT_COVERAGE_CHUNK_SIZE
    after = checkpoint.get("fm_id", 0)
    cursor.execute(
        "SELECT id, geom_id FROM feat_map WHERE fc_id = %s AND id > %s ORDER BY id LIMIT %s",
        [scope.object_id, after, limit],
    )
    rows = cursor.fetchall()
    if rows:
        cursor.execute(
            "DELETE FROM coverage WHERE geom_id = ANY(%s::int[])",
            [sorted({geom for _, geom in rows})],
        )
    if len(rows) < limit:
        return True, checkpoint
    checkpoint["fm_id"] = rows[-1][0]
    return False, checkpoint


# -- publish -------------------------------------------------------------------


_RETOKEN_SQL = """
    UPDATE extract_task_leases
    SET token = gen_random_uuid(), leased_until = now(), retry_after = now(),
        attempts = 0, last_error = NULL
    WHERE id = ANY(%s)
"""


def _publish(cursor, scope):
    if scope.kind == DATASET:
        _publish_dataset(cursor, scope)
    else:
        _publish_collection(cursor, scope)
    # Items logged by a later change wait on this scope's lock and commit
    # after us, with a new generation, so only reconciled ones are deleted.
    cursor.execute(
        "DELETE FROM extract_invalid_items WHERE scope_kind = %s AND scope_id = %s",
        [scope.kind, scope.object_id],
    )
    _mark_clean(cursor, scope)
    logger.info("Extract sync published %s %s generation %s", scope.kind, scope.object_id, scope.generation)


def _publish_dataset(cursor, scope):
    dataset_id = scope.object_id
    cursor.execute(
        "SELECT is_global, md5(ST_AsEWKB(spatial_extent)) FROM datasets WHERE id = %s",
        [dataset_id],
    )
    row = cursor.fetchone()
    # Coverage progress: only non-global datasets have one. Global ->
    # non-global starts it at 0; non-global -> global removes it.
    if row is None or row[0]:
        cursor.execute("DELETE FROM extract_coverage_progress WHERE dataset_id = %s", [dataset_id])
    else:
        cursor.execute(
            """
            INSERT INTO extract_coverage_progress (dataset_id, covered_up_to_fm_id, extent_hash)
            VALUES (%s, 0, %s)
            ON CONFLICT (dataset_id) DO UPDATE SET
                covered_up_to_fm_id = CASE WHEN %s::int IS NULL
                    THEN extract_coverage_progress.covered_up_to_fm_id
                    ELSE LEAST(extract_coverage_progress.covered_up_to_fm_id, %s::int) END,
                extent_hash = EXCLUDED.extent_hash
            """,
            [dataset_id, row[1], scope.rewind_from, scope.rewind_from],
        )
    if scope.rewind_from is not None:
        cursor.execute(
            """
            UPDATE extract_task_build_progress SET cursor_fm_id = %s
            WHERE id IN (
                SELECT id FROM extract_task_build_progress
                WHERE dataset_id = %s AND cursor_fm_id > %s
                ORDER BY id FOR UPDATE)
            """,
            [scope.rewind_from, dataset_id, scope.rewind_from],
        )
    if scope.items:
        # The logged options' and resources' current pairs lost the tasks the
        # reset deleted, anywhere in feature order: start them again. Sets
        # whose tasks were all request-linked are rescanned for nothing.
        cursor.execute(
            """
            UPDATE extract_task_build_progress SET cursor_fm_id = 0
            WHERE id IN (
                SELECT p.id FROM extract_task_build_progress p
                WHERE p.dataset_id = %(dataset_id)s AND p.current AND p.cursor_fm_id > 0
                  AND EXISTS (
                      SELECT 1 FROM extract_invalid_items i
                      WHERE i.scope_kind = 'dataset' AND i.scope_id = p.dataset_id
                        AND ((i.item_kind = 'option' AND i.item_id = p.po_id)
                             OR (i.item_kind = 'resource' AND i.item_id = ANY(p.resource_ids))))
                ORDER BY p.id FOR UPDATE)
            """,
            {"dataset_id": dataset_id},
        )
    if scope.reset_tasks or scope.reset_coverage or scope.items:
        # Leases captured the old epoch and can never complete; re-token and
        # expire them now, with fresh attempt budgets, instead of letting each
        # fail its completion check first. Additive changes leave them alone.
        cursor.execute(
            "SELECT id FROM extract_task_leases WHERE dataset_id = %s ORDER BY id FOR UPDATE",
            [dataset_id],
        )
        lease_ids = [r[0] for r in cursor.fetchall()]
        if lease_ids:
            cursor.execute(_RETOKEN_SQL, [lease_ids])


def _publish_collection(cursor, scope):
    rewind = scope.rewind_from
    if rewind is not None:
        # Lock every watermark and current pair before comparing, not just
        # those already past the rewind: a coverage chunk or lease claim in
        # flight may be about to move one past it. Its row lock makes us wait
        # for its commit, and the UPDATEs, as later statements, then see the
        # value it committed. (A dataset's own publish needs no such wait:
        # claims and chunks hold its state shared, which its sync excludes.)
        cursor.execute("SELECT 1 FROM extract_coverage_progress ORDER BY dataset_id FOR UPDATE")
        cursor.execute(
            "UPDATE extract_coverage_progress SET covered_up_to_fm_id = %s WHERE covered_up_to_fm_id > %s",
            [rewind, rewind],
        )
        # Every dataset, paused ones included: a paused pair's cursor must
        # also account for features it skipped while this collection was dirty.
        cursor.execute("SELECT 1 FROM extract_task_build_progress WHERE current ORDER BY id FOR UPDATE")
        cursor.execute(
            "UPDATE extract_task_build_progress SET cursor_fm_id = %s WHERE current AND cursor_fm_id > %s",
            [rewind, rewind],
        )
    # Leases holding a feature this change invalidated, or one that no
    # longer exists. Sync runs on the primary, so a missing feat_map row is a
    # confirmed deletion: drop it from the lease. Everything still required
    # stays in a lease, under a new token.
    cursor.execute(
        """
        SELECT l.id FROM extract_task_leases l
        WHERE EXISTS (
            SELECT 1 FROM unnest(l.fm_ids) AS f(id)
            LEFT JOIN feat_map fm ON fm.id = f.id
            WHERE fm.id IS NULL
               OR EXISTS (SELECT 1 FROM extract_invalid_items i
                          WHERE i.scope_kind = 'collection' AND i.scope_id = %s
                            AND i.item_kind = 'feature' AND i.item_id = f.id))
        ORDER BY l.id FOR UPDATE OF l
        """,
        [scope.object_id],
    )
    lease_ids = [r[0] for r in cursor.fetchall()]
    if lease_ids:
        cursor.execute(
            """
            UPDATE extract_task_leases l SET fm_ids = ARRAY(
                SELECT f FROM unnest(l.fm_ids) AS f
                WHERE EXISTS (SELECT 1 FROM feat_map fm WHERE fm.id = f)
                ORDER BY f)
            WHERE l.id = ANY(%s)
            """,
            [lease_ids],
        )
        cursor.execute(_RETOKEN_SQL, [lease_ids])
        cursor.execute(
            "DELETE FROM extract_task_leases WHERE id = ANY(%s) AND cardinality(fm_ids) = 0",
            [lease_ids],
        )


def _mark_clean(cursor, scope):
    table = "datasets" if scope.kind == DATASET else "feature_collections"
    cursor.execute(f"SELECT 1 FROM {table} WHERE id = %s", [scope.object_id])
    if cursor.fetchone() is None:
        # A tombstone: the source is gone and its effects are reconciled.
        cursor.execute(
            "DELETE FROM extract_input_state WHERE kind = %s AND object_id = %s AND generation = %s",
            [scope.kind, scope.object_id, scope.generation],
        )
        return
    cursor.execute(
        """
        UPDATE extract_input_state SET
            applied_generation = generation,
            rewind_from = NULL, sync_pairs = false, reset_tasks = false,
            reset_coverage = false, checkpoint = '{}'::jsonb, last_error = NULL,
            retry_after = now(), updated_at = clock_timestamp()
        WHERE kind = %s AND object_id = %s AND generation = %s
        """,
        [scope.kind, scope.object_id, scope.generation],
    )


_PHASES = {
    (DATASET, "pairs"): _phase_pairs,
    (DATASET, "reset_tasks"): _phase_dataset_reset_tasks,
    (DATASET, "reset_items"): _phase_dataset_reset_items,
    (DATASET, "reset_coverage"): _phase_dataset_reset_coverage,
    (COLLECTION, "reset_items"): _phase_collection_reset_items,
    (COLLECTION, "reset_coverage"): _phase_collection_reset_coverage,
}


def run_until_clean(max_chunks=10_000, deadline_seconds=None):
    """Run sync until nothing due is dirty (tests, initialization, repair).

    Stops early at ``deadline_seconds`` or when a pass makes no progress, so a
    scope locked elsewhere or backed off cannot spin it forever.
    """
    started = time.monotonic()
    total = 0
    while total < max_chunks:
        stats = sync_extract_work(max_chunks=min(1000, max_chunks - total))
        total += stats["chunks"]
        if not stats["chunks"]:
            return total
        if deadline_seconds is not None and time.monotonic() - started > deadline_seconds:
            return total
    return total


def health():
    """Dirty-scope health for metrics and the status command."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT kind,
                   count(*) FILTER (WHERE generation <> applied_generation),
                   count(*) FILTER (WHERE generation <> applied_generation AND last_error IS NOT NULL),
                   count(*) FILTER (WHERE bootstrap_pending),
                   COALESCE(EXTRACT(EPOCH FROM now() - min(updated_at)
                       FILTER (WHERE generation <> applied_generation)), 0)
            FROM extract_input_state GROUP BY kind
            """
        )
        return {
            kind: {"dirty": dirty, "erroring": erroring, "bootstrap_pending": boot,
                   "oldest_dirty_seconds": float(oldest)}
            for kind, dirty, erroring, boot, oldest in cursor.fetchall()
        }


__all__ = [
    "SyncConfigError", "desired_sets", "health", "reconcile_pairs",
    "run_until_clean", "sync_extract_work",
]
