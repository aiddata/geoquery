import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from itertools import pairwise
from pathlib import Path
from warnings import catch_warnings

import shapely
from django.db import (
    DataError, IntegrityError, InterfaceError, OperationalError, connection, transaction,
)

from analytics import metrics
from analytics.changes import UNAVAILABLE_SQL, Generations, lock_states
from datasets.models import DatasetResource

logger = logging.getLogger(__name__)


# Populated on first use from analytics.processors. The import is deferred because
# other containers import this module (the reaper, tests, the admin), but only the
# processing worker ever needs rasterstats/geopandas.
_registry = None


def get_func(op):
    """Get the processor function for the given operation name."""
    global _registry
    if _registry is None:
        from analytics.processors import REGISTRY

        _registry = REGISTRY
    func = _registry.get(op)
    if func is None:
        raise ValueError(f"Operation {op} not supported.")
    return func


_batch_registry = None


def get_batch_func(op):
    """The processor's batch form, or None if it only runs one feature at a time."""
    global _batch_registry
    if _batch_registry is None:
        from analytics.processors import BATCH_REGISTRY

        _batch_registry = BATCH_REGISTRY
    return _batch_registry.get(op)


def _op_kwargs(short_name, po_kwargs, task_kwargs):
    """Keyword arguments for one processor call, including the result name.

    A task with its own kwargs gets a name suffixed by their hash, so its
    columns never collide with the default task's for the same option.
    """
    op_kwargs = {"name": short_name}
    if po_kwargs:
        op_kwargs.update(po_kwargs)
    if task_kwargs:
        op_kwargs.update(task_kwargs)
        kwargs_hash = hashlib.md5(
            json.dumps(task_kwargs, sort_keys=True).encode()
        ).hexdigest()[:8]
        op_kwargs["name"] = f"{short_name}_{kwargs_hash}"
    return op_kwargs


def _classify_value(value):
    """Return (column, coerced) for a raw processor result, or None for nodata.

    None is nodata, not a value: it becomes SQL NULL. Before this, the
    fallthrough below stringified it, and 210,329,319 production rows carried
    the literal text 'None' -- which merge.py's `values[i] is None` guard does
    not catch, so it reached user downloads as the string "None".

    int before float (order matters -- bool would otherwise be misfiled as
    int, but processors never return bool here so it's not a live concern),
    anything that isn't int/float/str is stringified rather than dropped.

    Numbers are coerced to the exact built-in type, as the ORM's
    get_prep_value used to do: COPY dumps each value by its Python type, and
    a subclass (numpy.float64, bool) must reach it as the plain number.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return "int", int(value)
    if isinstance(value, float):
        return "float", float(value)
    if isinstance(value, str):
        return "str", value
    return "str", str(value)


def _column_for(values_by_pos):
    """Pick the value column for one name, from its first non-nodata value.

    Returns None when every position is nodata -- the row is still written, so
    that "we ran this and found nothing" stays distinguishable from "we never
    ran this", but no value column is populated.

    Deliberately the first NON-None value rather than simply the first: a
    leading nodata used to type the whole row 'str' and silently coerce every
    real value after it into the varchar array.
    """
    for i in sorted(values_by_pos):
        classified = _classify_value(values_by_pos[i])
        if classified is not None:
            return classified[0]
    return None


# Coerces a grouped row's elements to the column _column_for picked, as
# ArrayField's per-element get_prep_value used to: COPY cannot dump a list of
# mixed Python types, so [1.5, 0] must reach it as [1.5, 0.0].
_COERCE = {"int": int, "float": float, "str": str}


def _result_rows(produced, n, *, prefix, label):
    """COPY-ready result rows from ``{name: {position: value}}``.

    ``prefix`` is the leading (extract_task_id, dataset_id) pair of every row;
    a lease page builds rows before its task ids exist and substitutes them
    at completion. One row per name, even when every position is nodata: the
    row records that the extraction ran. A single-resource row uses the
    scalar column of the type its value picked; a grouped row uses the array
    column of the type its first non-nodata value picked, position-aligned
    with resource_ids.
    """
    rows = []
    for name, values_by_pos in produced.items():
        row = list(prefix) + [name] + [None] * (len(_RESULT_COLUMNS) - 3)
        column = _column_for(values_by_pos)
        if column is not None:
            if n == 1:
                classified = _classify_value(values_by_pos.get(0))
                if classified is not None:
                    row[_RESULT_INDEX[f"{column}_value"]] = classified[1]
            else:
                values = [None] * n
                for i, value in values_by_pos.items():
                    classified = _classify_value(value)
                    if classified is not None:
                        if classified[0] != column:
                            logger.warning(
                                "%s name %s position %d: %s value in a %s "
                                "row. Coerced to the row's type; a genuinely "
                                "incompatible value raises here. A name is "
                                "assumed to produce one type across every "
                                "position.",
                                label, name, i, classified[0], column,
                            )
                        values[i] = _COERCE[column](classified[1])
                row[_RESULT_INDEX[f"{column}_values"]] = values
        rows.append(tuple(row))
    return rows


def _failure_summary(failures):
    """The task error for ``[(resource_id, position, exc), ...]``, or None."""
    if not failures:
        return None
    return "; ".join(f"resource {rid}[{i}]: {exc!r}" for rid, i, exc in failures)[:100]


# Distinct from accounts.adopt_auth_user's ADVISORY_LOCK_ID (8419307742115) --
# any int8 works for pg_advisory_xact_lock as long as it doesn't collide with
# another lock use in the codebase.
CLAIM_LOCK_ID = 8419307742201


def _claim_batch_size():
    """How many tasks one claim grabs: the size of a worker's chunk.

    Every claim serializes on CLAIM_LOCK_ID, and a claimer waiting for that
    lock holds a pgBouncer server connection while it waits. When every task
    claimed for itself, the fleet issued one claim per task completed --
    measured in production as 32 of 39 active connections parked on this lock
    doing nothing, which starved every other workload sharing the pooler
    (request builds, MCP) of connections. Claiming B tasks at a time divides
    both the lock acquisitions and those parked connections by B.
    """
    from django.conf import settings

    return max(1, getattr(settings, "EXTRACT_TASK_CLAIM_BATCH", 4))


_ASYNC_COMMIT = "SET LOCAL synchronous_commit = off; "


def _synchronous_commit():
    from django.conf import settings

    return getattr(settings, "EXTRACT_TASK_SYNCHRONOUS_COMMIT", False)


def _execute_async(cursor, sql, params):
    """Execute ``sql`` so that its transaction commits without waiting for fsync.

    See EXTRACT_TASK_SYNCHRONOUS_COMMIT in settings for why this is safe here.

    The SET LOCAL rides in the same execute as the statement. Django's psycopg
    cursors bind parameters client-side and send the string in one round
    trip, which PostgreSQL runs as a single transaction -- an implicit one
    under autocommit -- so this costs nothing over the bare statement. SET
    LOCAL, never SET: a session-level SET would stay on the pooled server
    connection and make whichever workload reuses it non-durable. Enabling
    server_side_binding would make this raise rather than silently commit
    synchronously, since a prepared statement cannot hold two commands.

    The cursor is left on the statement's own result, not the SET's.
    """
    if _synchronous_commit():
        cursor.execute(sql, params)
        return
    cursor.execute(_ASYNC_COMMIT + sql, params)
    cursor.nextset()


def claim_pending_tasks(limit=1):
    """Move up to ``limit`` pending tasks (status=0) straight to running (status=2).

    Returns the claimed ``(id, dataset_id)`` pairs, highest priority then
    oldest first (ties broken by id). The caller -- a worker about to run them
    -- owns these rows from here: it runs each one (see _run_extract_task), and
    returns any it didn't get to with _release_claimed_tasks. A row whose
    worker died without releasing it is returned to pending by
    free_stale_processing_tasks. Because the rows are claimed in the same
    transaction that selects them, concurrent callers get disjoint sets: FOR
    UPDATE SKIP LOCKED steps past rows another transaction is claiming rather
    than waiting on them or handing out the same row twice.

    The `, id` tiebreaker matters at scale: bulk inserts (a request's
    materialization, and once the builder) share one NOW() per statement, so
    many rows can carry the exact same (priority, submit_time). Without a deterministic tiebreaker,
    concurrent SKIP LOCKED scans have no stable order to partition across a
    large tied group -- every claimer effectively circles the same ambiguous
    block instead of cleanly dividing sequential work, and skip-distance
    grows with the tied-group size rather than just the concurrency level.
    `id` is already unique and monotonic, so it's a free, always-available
    tiebreaker -- see migration 0025, which adds it to
    extract_tasks_pending_idx so this ORDER BY can still be served by an
    index-only scan of the partial index rather than falling back to a sort.

    The id tiebreaker alone wasn't enough at production scale: when every
    worker slot claimed for itself the instant it finished a task, ~150+
    slots meant dozens of transactions concurrently racing FOR UPDATE SKIP
    LOCKED over the same handful of leading index rows -- each one has to
    step past every row the others have already locked, so the work to find
    an open row grows with the number of simultaneous claimers, not the
    backlog. pg_advisory_xact_lock forces those transactions to queue up and
    claim one at a time instead of fighting over the same rows in parallel.
    The lock is transaction-scoped (held for exactly the duration of the
    claim below) and releases automatically on commit, including on
    exception.

    Neither of those was the dominant cost, though. extract_tasks is LIST
    partitioned on dataset_id, which the claim doesn't know ahead of time --
    a single `UPDATE extract_tasks SET ... WHERE id IN (SELECT ... FOR
    UPDATE SKIP LOCKED LIMIT %s)` statement can't prune partitions on `id`
    alone, so Postgres re-runs the entire inner SELECT once per partition's
    per-partition Update node (the SKIP LOCKED subquery has row-locking side
    effects, so its result can't be cached and reused across those checks)
    -- O(partitions^2) scans for a single claim. Measured on production (58
    partitions, ~76M pending rows): 4.1 seconds for one row, matching the
    "3-6 second claim statements" seen both before and after the advisory
    lock above went in -- this was the actual bottleneck the whole time,
    serialized or not. Splitting into two statements fixes it: the SELECT
    below already returns dataset_id (the partition key) alongside id, so
    the UPDATE can join on (dataset_id, id) and let Postgres prune straight
    to the owning partition per row -- confirmed via EXPLAIN ANALYZE: 0.2ms
    versus 4.1s for the same claim.

    The ids reach the UPDATE as two aligned arrays rather than a VALUES list.
    A third array lists the distinct dataset ids so unrelated partitions can
    be excluded during planning, without relying on execution-time pruning
    through the join. The parameter count stays constant at any batch size.
    What does grow with ``limit`` is the time the lock is held: the
    SELECT's cost is mostly fixed (merge-appending every partition's index
    head), but locking and updating the rows is per row.

    Timed in two stages: waiting for the lock, and holding it through commit.
    The second is what the whole fleet queues behind, so its rate caps claims
    per second -- which is also why the claim commits asynchronously: a
    commit that waits for fsync holds the lock for the whole flush.

    Candidates come from extract_runnable_tasks, the same definition the
    autoscaler counts (migration 0031): pending, valid (no reset pending for
    them), every input active and available, and a request's or a current
    pair's. The candidates' input states are then share-locked (see
    analytics.changes, which also gives the lock order) and rechecked before
    any task row is locked: the advisory lock first, then the guards, then
    the tasks. Available datasets are passed as an explicit list so their
    partitions are pruned at planning time and an unavailable partition's
    backlog is never walked.
    """
    started = time.perf_counter()
    with transaction.atomic():
        with connection.cursor() as cursor:
            _execute_async(cursor, "SELECT pg_advisory_xact_lock(%s)", [CLAIM_LOCK_ID])
            locked = time.perf_counter()
            cursor.execute(_CLEAN_ACTIVE_DATASETS_SQL)
            clean_datasets = [r[0] for r in cursor.fetchall()]
            rows = []
            if clean_datasets:
                cursor.execute(_DISCOVER_PENDING_SQL, [clean_datasets, limit])
                candidates = cursor.fetchall()
                rows = _lock_candidates(cursor, candidates)
            if rows:
                # Keep the pair join for row identity, and the explicit
                # dataset filter for plan-time partition pruning.
                cursor.execute(
                    """
                    UPDATE extract_tasks AS t
                    SET status = 2, update_time = NOW()
                    FROM unnest(%s::int[], %s::bigint[]) AS v(dataset_id, id)
                    WHERE t.dataset_id = v.dataset_id AND t.id = v.id
                      AND t.dataset_id = ANY(%s::int[])
                    """,
                    _ref_arrays(rows),
                )
    metrics.DISPATCH_SECONDS.labels("lock_wait").observe(locked - started)
    metrics.DISPATCH_SECONDS.labels("claim").observe(time.perf_counter() - locked)
    return rows


_CLEAN_ACTIVE_DATASETS_SQL = f"""
    SELECT d.id FROM datasets d
    JOIN extract_input_state s ON s.kind = 'dataset' AND s.object_id = d.id
    WHERE d.active AND NOT {UNAVAILABLE_SQL}
    ORDER BY d.id
"""

# Discovery, without locks, through the definition claims and demand share.
_DISCOVER_PENDING_SQL = """
    SELECT id, dataset_id, fc_id
    FROM extract_runnable_tasks
    WHERE dataset_id = ANY(%s::int[])
    ORDER BY priority DESC, submit_time ASC, id ASC
    LIMIT %s
"""


def _lock_candidates(cursor, candidates):
    """Guard the candidates' scopes, then lock the tasks that are still pending.

    Returns ``(id, dataset_id)`` refs in claim order. A scope a writer holds,
    or that turned dirty since discovery, drops its candidates.
    """
    if not candidates:
        return []
    guard = lock_states(
        {dataset_id for _, dataset_id, _ in candidates},
        {fc_id for _, _, fc_id in candidates},
        cursor=cursor,
    )
    refs = [
        (task_id, dataset_id)
        for task_id, dataset_id, fc_id in candidates
        if dataset_id in guard.clean.datasets and fc_id in guard.clean.collections
    ]
    if not refs:
        return []
    cursor.execute(
        """
        SELECT t.id, t.dataset_id FROM extract_tasks t
        JOIN unnest(%s::int[], %s::bigint[]) AS v(dataset_id, id)
          ON t.dataset_id = v.dataset_id AND t.id = v.id
        WHERE t.status = 0 AND t.dataset_id = ANY(%s::int[])
        ORDER BY t.priority DESC, t.submit_time ASC, t.id ASC
        FOR UPDATE OF t SKIP LOCKED
        """,
        _ref_arrays(refs),
    )
    return cursor.fetchall()


def _ref_arrays(refs):
    """Return aligned dataset/id arrays and distinct datasets for pruning.

    Every statement that unnests these casts the id array to bigint[], never
    int[]: task ids passed int4's range when extract_tasks_id_seq ran out at
    2,147,483,647, and an int[] cast would overflow on the first id above it.
    """
    dataset_ids = [dataset_id for _, dataset_id in refs]
    return [dataset_ids, [task_id for task_id, _ in refs], sorted(set(dataset_ids))]


def _release_claimed_tasks(refs, claimed_at=None):
    """Return claimed tasks a worker will not run to pending (status=0).

    For a worker shutting down, or a chunk abandoned on an error: the rows go
    straight back to the queue instead of waiting out STALE_TASK_MINUTES for
    free_stale_processing_tasks. Only rows still running (status=2) are
    touched, so a task that finished, failed, or was already reaped is left
    alone. With ``claimed_at`` (one claim stamp per ref) the release is also
    fenced on the claim, so a task reclaimed by another worker is not taken
    back from it. Commits asynchronously like the claim; if the commit is
    lost in a crash, the reaper returns the rows anyway.
    """
    if not refs:
        return 0
    dataset_ids, task_ids, datasets = _ref_arrays(refs)
    stamps = list(claimed_at) if claimed_at is not None else [None] * len(refs)
    with connection.cursor() as cursor:
        _execute_async(
            cursor,
            """
            UPDATE extract_tasks AS t
            SET status = 0, update_time = NOW()
            FROM unnest(%s::int[], %s::bigint[], %s::timestamptz[]) AS v(dataset_id, id, claimed_at)
            WHERE t.dataset_id = v.dataset_id AND t.id = v.id AND t.status = 2
              AND (v.claimed_at IS NULL OR t.update_time = v.claimed_at)
              AND t.dataset_id = ANY(%s::int[])
            """,
            [dataset_ids, task_ids, stamps, datasets],
        )
        return cursor.rowcount


def _positions_needing_processing(n):
    """Every index into resource_ids (0..n-1). A retry recomputes all of them.

    This used to skip positions whose value was already non-NULL, reading an
    array NULL as "position i still needs work". That reading is gone: a NULL
    now means the extraction ran and found nodata, which is a final answer,
    not a request to retry. Telling those apart again would need a separate
    per-position marker.

    The only thing the skip bought was avoiding recomputation of
    already-successful resources on a grouped task's retry. That is free for
    single-position tasks (nothing to skip) and is paid only by grouped ones,
    and only when they actually fail. Do NOT reintroduce the skip without
    adding an explicit attempted-marker first -- without one it silently
    resurrects the infinite-retry bug for every nodata result.
    """
    return set(range(n))


# extract_data's columns, in the order _extract builds result rows and
# _persist_outcomes copies them.
_RESULT_COLUMNS = (
    "extract_task_id", "dataset_id", "name",
    "int_value", "float_value", "str_value",
    "int_values", "float_values", "str_values",
)
_RESULT_INDEX = {column: i for i, column in enumerate(_RESULT_COLUMNS)}
_COPY_RESULTS = f"COPY extract_data ({', '.join(_RESULT_COLUMNS)}) FROM STDIN"


@dataclass
class _TaskOutcome:
    task_id: int
    dataset_id: int
    claimed_at: datetime | None
    rows: list[tuple]  # in _RESULT_COLUMNS order
    status: int
    error: str | None
    timer: metrics.TaskTimer
    # The input generations the task was loaded under, and the collection
    # they include. None only for outcomes built by hand.
    generations: Generations | None = None


def _run_extract_task(task_id, dataset_id=None, *, outcomes=None):
    """Compute a task; buffer its writes when called by the chunk worker.

    Manual callers still persist immediately. Exceptions keep their original
    types, but a loaded task's failure is buffered before it is re-raised.
    Buffered outcomes retain no exception tracebacks or processor inputs.
    """
    immediate = outcomes is None
    if immediate:
        outcomes = []
    before = len(outcomes)
    timer = metrics.TaskTimer(dataset_id)
    try:
        return _extract(task_id, dataset_id, timer, outcomes)
    finally:
        timer.enter(None)  # time in the buffer is not active task work
        if len(outcomes) == before:
            timer.finish()  # unavailable, or an exception before loading
        elif immediate:
            _flush_outcomes(outcomes)


def _persist_outcomes(outcomes):
    """Atomically finalize a batch and replace its results, pruning every query.

    One UPDATE both rechecks each claim and writes the terminal status: a
    task buffered earlier in a long chunk may have been reset or reclaimed,
    so only rows still running under the claim this worker loaded are
    finalized, and RETURNING names them. Only those tasks' results are
    replaced. This used to be a SELECT ... FOR UPDATE and then per-dataset
    UPDATEs, but the lock pass wrote WAL for every row and gave nothing the
    UPDATE's own row locks don't. The arrays are sorted, so a nested-loop
    plan locks rows in a consistent order. A deadlock that gets through
    anyway is an OperationalError, which _flush_outcomes retries.

    Results go in with COPY, from tuples built as each task finished. On
    production (2026-10-03, 2048-task chunks of ~11,500 rows) bulk_create
    spent ~2.5 s of each flush building SQL in Python while the transaction
    held its row locks and a pooler server connection: ~2.4 backends sat
    idle in transaction on average. Locally the same rows took 670 ms with
    bulk_create and 20 ms with COPY.

    Inputs are fenced too: the dataset and collection states each task was
    loaded under are share-locked, and a task whose inputs changed since (a
    different generation, or a scope now dirty or held by a writer) is not
    finalized. Its claim is released in the same transaction, fenced on the
    claim stamp, and the claim filter keeps it waiting until sync has
    reconciled the change.

    Locks last only for persistence, never extraction. Empty row sets
    preserve old results, including when every resource failed on a retry.
    """
    if not outcomes:
        return
    ordered = sorted(outcomes, key=lambda o: (o.dataset_id, o.task_id))
    accepted = []
    # (phase, wall, cpu) at each boundary. The recheck and status UPDATE and
    # the commit are finalize; replacing results is write.
    marks = [("finalize", time.perf_counter(), time.process_time())]
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # The first statement carries the SET LOCAL for the whole
                # transaction: the input guard if there is one, else the
                # status UPDATE.
                prefix = "" if _synchronous_commit() else _ASYNC_COMMIT
                ordered, stale, guarded = _fence_inputs(cursor, ordered, prefix)
                if stale:
                    _release_claimed_tasks(
                        [(o.task_id, o.dataset_id) for o in stale],
                        [o.claimed_at for o in stale],
                    )
                dataset_ids = [o.dataset_id for o in ordered]
                (cursor.execute if guarded else partial(_execute_async, cursor))(
                    """
                    UPDATE extract_tasks AS t
                    SET status = v.status, error = v.error,
                        complete_time = CASE WHEN v.status = 1
                            THEN STATEMENT_TIMESTAMP() ELSE t.complete_time END
                    FROM unnest(%s::int[], %s::bigint[], %s::timestamptz[], %s::int[], %s::text[])
                        AS v(dataset_id, id, claimed_at, status, error)
                    WHERE t.dataset_id = v.dataset_id AND t.id = v.id
                      AND t.status = 2 AND t.update_time IS NOT DISTINCT FROM v.claimed_at
                      AND t.dataset_id = ANY(%s::int[])
                    RETURNING t.dataset_id, t.id
                    """,
                    [
                        dataset_ids, [o.task_id for o in ordered],
                        [o.claimed_at for o in ordered], [o.status for o in ordered],
                        [o.error for o in ordered], sorted(set(dataset_ids)),
                    ],
                )
                claimed = set(cursor.fetchall())
                accepted = [o for o in ordered if (o.dataset_id, o.task_id) in claimed]
                marks.append(("write", time.perf_counter(), time.process_time()))
                replacing = [o for o in accepted if o.rows]
                if replacing:
                    cursor.execute(
                        """
                        DELETE FROM extract_data AS d
                        USING unnest(%s::int[], %s::bigint[]) AS v(dataset_id, id)
                        WHERE d.dataset_id = v.dataset_id AND d.extract_task_id = v.id
                          AND d.dataset_id = ANY(%s::int[])
                        """,
                        _ref_arrays([(o.task_id, o.dataset_id) for o in replacing]),
                    )
                    # Django translates driver errors only on its own cursor
                    # methods, and _flush_outcomes splits on DataError.
                    with connection.wrap_database_errors, cursor.copy(_COPY_RESULTS) as copy:
                        for outcome in replacing:
                            for row in outcome.rows:
                                copy.write_row(row)
            marks.append(("finalize", time.perf_counter(), time.process_time()))
    finally:
        marks.append((None, time.perf_counter(), time.process_time()))
        # Amortize actual flush work across tasks; never multiply it by the
        # batch size or count time spent waiting in the in-memory buffer.
        for (phase, wall, cpu), (_, next_wall, next_cpu) in pairwise(marks):
            for outcome in outcomes:
                outcome.timer.add(
                    phase, (next_wall - wall) / len(outcomes),
                    (next_cpu - cpu) / len(outcomes),
                )

    accepted_ids = {(o.dataset_id, o.task_id) for o in accepted}

    def record_committed():
        for outcome in outcomes:
            if (outcome.dataset_id, outcome.task_id) not in accepted_ids:
                outcome.timer.outcome = "unavailable"
            else:
                outcome.timer.outcome = "completed" if outcome.status == 1 else "failed"
            outcome.timer.finish()

    transaction.on_commit(record_committed)


def _fence_inputs(cursor, ordered, prefix=""):
    """Split outcomes into those whose inputs are unchanged and the rest.

    Takes the share locks (see analytics.changes) for every scope the
    outcomes were loaded under; they last until the persist transaction
    ends. Returns ``(current, stale, guarded)``, guarded meaning a guard
    statement ran (carrying ``prefix``).
    """
    expected = [o for o in ordered if o.generations is not None]
    if not expected:
        return ordered, [], False
    datasets = {d for o in expected for d in o.generations.datasets}
    collections = {c for o in expected for c in o.generations.collections}
    guard = lock_states(datasets, collections, cursor=cursor, prefix=prefix)

    def current(outcome):
        if outcome.generations is None:
            return True
        return all(
            guard.clean.datasets.get(d) == g for d, g in outcome.generations.datasets.items()
        ) and all(
            guard.clean.collections.get(c) == g for c, g in outcome.generations.collections.items()
        )

    kept = [o for o in ordered if current(o)]
    stale = [o for o in ordered if not current(o)]
    if stale:
        logger.info("Deferring %d task outcomes whose inputs changed since they were loaded", len(stale))
    return kept, stale, True


def _flush_outcomes(outcomes):
    """Retry transient failures without recomputing; isolate invalid results.

    An exhausted connection retry propagates to the worker, which releases
    unresolved claims. Only data/encoding errors split the batch; a database
    outage must not trigger a storm of single-task writes.
    """
    if not outcomes:
        return
    for attempt in range(3):
        try:
            _persist_outcomes(outcomes)
            return
        except (OperationalError, InterfaceError):
            if attempt == 2:
                metrics.FLUSH_FAILURES.inc()
                raise
            metrics.FLUSH_RETRIES.inc()
            logger.warning("Retrying extract result flush", exc_info=True)
            if not connection.in_atomic_block:
                connection.close()
            time.sleep(0.25 * 2 ** attempt)
        except (DataError, IntegrityError, ValueError, TypeError, OverflowError) as exc:
            if len(outcomes) > 1:
                middle = len(outcomes) // 2
                _flush_outcomes(outcomes[:middle])
                _flush_outcomes(outcomes[middle:])
            else:
                outcome = outcomes[0]
                logger.exception("Could not store results for task %s", outcome.task_id)
                # The failed transaction restored any previous results.
                # Persist only the error, leaving those results intact.
                if not outcome.rows:
                    raise
                outcome.rows = []
                outcome.status = -1
                outcome.error = repr(exc)[:100]
                _flush_outcomes(outcomes)
            return


@dataclass(frozen=True)
class _ClaimedTask:
    dataset_id: int
    resource_ids: list[int]
    kwargs: dict | None
    function: str
    short_name: str
    po_kwargs: dict | None
    geometry_wkb: bytes
    claimed_at: datetime | None
    generations: Generations | None = None


def _load_claimed_task(task_id, dataset_id=None):
    """Return the inputs of a task this worker claimed, in one statement.

    The task is already running (status=2): claim_pending_tasks moved it there
    under the claim lock, so this only reads. It used to be the claim itself
    -- an UPDATE from queued (3) to running (2) -- which cost every task a
    second non-HOT write to extract_tasks (see database.md §3) on top of the
    batch claim and the final status. A row that is no longer running (reaped
    and finished elsewhere, or reset by hand) is not returned, and neither is
    one whose dataset, processing option or feature collection has been
    deactivated since it was created. The PostGIS geometry is returned as WKB
    for Shapely directly.

    The task's dataset and collection epochs are read in the same statement
    as its current collection and inputs, so they describe what was actually
    loaded, whatever the claim guarded. A task with a reset pending (not in
    extract_valid_tasks), or whose dataset or collection is unavailable, is
    not returned: the caller defers it rather than failing it.
    _persist_outcomes checks the epochs again before anything is written.

    Name the partition: ``dataset_id`` comes from the claim, and filtering on
    it prunes the lookup to one partition. None is accepted (tests, manual
    runs) but cannot prune.
    """
    partition_filter = "AND t.dataset_id = %s" if dataset_id is not None else ""
    params = [task_id]
    if dataset_id is not None:
        params.append(dataset_id)

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT t.dataset_id, t.resource_ids, t.kwargs::text,
                   po.function, po.short_name, po.kwargs::text,
                   ST_AsBinary(g.shape), t.update_time,
                   fm.fc_id, sd.epoch, sc.epoch
            FROM extract_valid_tasks AS t
            JOIN datasets AS d ON d.id = t.dataset_id
            JOIN processing_options AS po ON po.id = t.po_id
            JOIN feat_map AS fm ON fm.id = t.fm_id
            JOIN feature_collections AS fc ON fc.id = fm.fc_id
            JOIN features AS g ON g.id = fm.geom_id
            JOIN extract_input_state AS sd
              ON sd.kind = 'dataset' AND sd.object_id = t.dataset_id
            JOIN extract_input_state AS sc
              ON sc.kind = 'collection' AND sc.object_id = fm.fc_id
            WHERE t.id = %s {partition_filter}
              AND t.status = 2
              AND d.active AND po.active AND fc.active
              AND NOT (sd.reset_tasks OR sd.reset_coverage OR sd.bootstrap_pending)
              AND NOT (sc.reset_tasks OR sc.reset_coverage OR sc.bootstrap_pending)
            """,
            params,
        )
        row = cursor.fetchone()

    if row is None:
        return None
    (dataset_id, resource_ids, kwargs, function, short_name, po_kwargs, wkb,
     claimed_at, fc_id, dataset_generation, collection_generation) = row
    return _ClaimedTask(
        dataset_id=dataset_id,
        resource_ids=resource_ids,
        kwargs=json.loads(kwargs) if kwargs is not None else None,
        function=function,
        short_name=short_name,
        po_kwargs=json.loads(po_kwargs) if po_kwargs is not None else None,
        geometry_wkb=bytes(wkb),
        claimed_at=claimed_at,
        generations=Generations(
            datasets={dataset_id: dataset_generation},
            collections={fc_id: collection_generation},
        ),
    )


def _extract(task_id, dataset_id, timer, outcomes):
    """Load a claimed task, run its resources, and buffer results and status.

    Accepts rows this worker claimed (running, 2). On success (no position raised
    this run) status is set to 1; otherwise -1 with a summary of what failed.
    A NULL value is nodata, a final answer, and does not hold a task back.
    Each resource_ids[i] is processed independently -- one
    resource's exception is caught and leaves that position NULL rather than
    aborting the others in the same run (see the per-resource try/except
    below) or failing the task outright (see the conditional re-raise at the
    bottom).

    ``dataset_id`` is the task's partition key, from the claim. None is
    accepted; the lookup still works, it just can't prune.
    """
    logger.info("Running extract task %s", task_id)

    task = _load_claimed_task(task_id, dataset_id)
    if task is None:
        logger.info(
            "Task %s is not available (no longer running, filtered out, or its "
            "inputs are changing); releasing it",
            task_id,
        )
        timer.outcome = "unavailable"
        if dataset_id is not None:
            # Still status 2 only if this worker's claim survives. Returning
            # it now, rather than leaving it for the stale-task reaper, is
            # what defers a task whose inputs went dirty after its claim.
            _release_claimed_tasks([(task_id, dataset_id)])
        return None
    timer.dataset_id = task.dataset_id

    # Setup (resolving resources/func/geometry) and the merge-into-ExtractData
    # step can both raise unexpectedly; catch that the same way the old code
    # did, marking -1 with repr(exc) and re-raising. Per-resource processing
    # failures are handled separately inside the loop below and never reach
    # this except -- they're expected, not exceptional.
    timer.enter("load")
    try:
        # id__in does not preserve input order, so resources must be
        # re-ordered against task.resource_ids by dict lookup: position i
        # here has to line up with position i in every ExtractData row's
        # value arrays for this task (see ExtractTask/ExtractData docstrings).
        by_id = {
            r.id: r
            for r in DatasetResource.objects.filter(
                id__in=task.resource_ids
            ).select_related("dataset")
        }
        resources = [by_id[rid] for rid in task.resource_ids]
        # Every resource in one task's resource_ids belongs to the same
        # dataset by construction (pair sync groups within a dataset, and
        # requests create single-resource tasks), so any one of them stands
        # in for it.
        dataset = resources[0].dataset
        func = get_func(task.function)

        geometry = shapely.from_wkb(task.geometry_wkb)

        n = len(task.resource_ids)
        positions = _positions_needing_processing(n)

        # name -> {position: value}, accumulated only from calls that
        # succeeded this run. A resource whose call raises contributes
        # nothing here, so its position stays/becomes NULL in every name's
        # array below rather than blocking the other positions.
        produced = {}
        failures = []  # (resource_id, position, exc) for each call that raised this run

        timer.enter("extract")
        for i in sorted(positions):
            resource = resources[i]
            dataset_path = Path(dataset.path) / resource.path

            op_kwargs = _op_kwargs(task.short_name, task.po_kwargs, task.kwargs)

            if dataset.mapped:
                # A query per resource, so it counts as load, not extract.
                timer.enter("load")
                op_kwargs["category_map"] = dict(
                    dataset.mappings.values_list("map_val", "map_name")
                )
                timer.enter("extract")

            try:
                with catch_warnings(record=True) as warnings:
                    results = func(geometry, dataset_path, **op_kwargs)
                    for w in warnings:
                        logger.warning(
                            "Warning in task %s resource %s: %s",
                            task_id, resource.id, w.message,
                        )
            except Exception as exc:
                logger.warning(
                    "Task %s resource %s (position %d) failed: %s",
                    task_id, resource.id, i, exc,
                )
                failures.append((resource.id, i, exc))
                continue

            for name, value in results:
                produced.setdefault(name, {})[i] = value

        timer.enter("write")
        # Every position is recomputed (see _positions_needing_processing), so
        # this run's results are the complete picture for this task. Replace
        # the row set wholesale rather than merging into whatever a previous
        # run left behind.
        #
        # A position that raised while others succeeded still lands as NULL
        # here, indistinguishable from nodata at the row level. That is
        # acceptable because every reader of results (merge, visualize,
        # explore) gates on status=1, so a failed task's rows are never read.
        # What broadens is the MEANING of an empty cell, from "failed or not
        # yet processed" to "failed or nodata". Both render identically.
        #
        # Rows are plain tuples in _RESULT_COLUMNS order, ready for COPY, so
        # none of this work happens inside the flush transaction.
        rows = _result_rows(
            produced, n, prefix=(task_id, task.dataset_id), label=f"Task {task_id}"
        )

        all_names = set(produced)

    except Exception as exc:
        logger.exception("Task %s failed: %s", task_id, exc)
        outcomes.append(_TaskOutcome(
            task_id, task.dataset_id, task.claimed_at, [], -1, repr(exc)[:100], timer,
            task.generations,
        ))
        raise

    incomplete_positions = {i for _, i, _ in failures}
    error = _failure_summary(failures)
    outcomes.append(_TaskOutcome(
        task_id, task.dataset_id, task.claimed_at, rows,
        -1 if failures else 1, error, timer, task.generations,
    ))
    if not failures:
        return {"task_id": task_id, "results": len(all_names)}

    logger.warning(
        "Task %s incomplete: positions %s still outstanding after this run",
        task_id, sorted(incomplete_positions),
    )

    # Re-raise only when this run produced literally nothing -- that's what
    # reproduces the pre-redesign behavior for a standard 1-element task
    # exactly (its one resource fails => status=-1 AND the exception
    # propagates to Celery). A grouped task with at least one successful
    # position is a genuine partial result worth keeping; raising on top of
    # it would only blow up the Celery task without adding any information
    # the -1 status + error field don't already carry.
    if failures and not produced:
        if len(failures) == 1:
            # Exactly one resource attempted and failed -- reproduce the
            # pre-redesign bare `raise` exactly: the original exception's
            # type, message, and traceback all propagate unchanged, instead
            # of being flattened into a synthesized RuntimeError.
            raise failures[0][2]
        # More than one position failed this run; there's no single original
        # exception to reproduce, so synthesize a summary -- but chain it to
        # the last original exception so the real cause is still visible.
        raise RuntimeError(error) from failures[-1][2]

    return {"task_id": task_id, "results": len(all_names)}
