import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from warnings import catch_warnings

import shapely
from celery import shared_task
from django.db import connection, transaction

from analytics import metrics
from analytics.models import ExtractData, ExtractTask
from datasets.models import DatasetResource

logger = logging.getLogger(__name__)


# Populated on first use from analytics.processors. The import is deferred because
# Celery autodiscovery loads this module in every container, but only the processing
# worker ever needs rasterstats/geopandas.
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


def _classify_value(value):
    """Return (column, coerced) for a raw processor result, or None for nodata.

    None is nodata, not a value: it becomes SQL NULL. Before this, the
    fallthrough below stringified it, and 210,329,319 production rows carried
    the literal text 'None' -- which merge.py's `values[i] is None` guard does
    not catch, so it reached user downloads as the string "None".

    int before float (order matters -- bool would otherwise be misfiled as
    int, but processors never return bool here so it's not a live concern),
    anything that isn't int/float/str is stringified rather than dropped.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return "int", value
    if isinstance(value, float):
        return "float", value
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


# Distinct from accounts.adopt_auth_user's ADVISORY_LOCK_ID (8419307742115) --
# any int8 works for pg_advisory_xact_lock as long as it doesn't collide with
# another lock use in the codebase.
CLAIM_LOCK_ID = 8419307742201


def _claim_batch_size():
    """How many tasks one claim grabs, and so how many ride in one message.

    Every claim serializes on CLAIM_LOCK_ID, and a claimer waiting for that
    lock holds a pgBouncer server connection while it waits. run_extract_task
    self-chains, so with N worker slots the fleet issues one claim per task
    completed -- measured in production as 32 of 39 active connections parked
    on this lock doing nothing, which starved every other workload sharing
    the pooler (request builds, MCP) of connections. Claiming B tasks per
    message divides both the lock acquisitions and those parked connections
    by B.
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
    """Move up to ``limit`` pending tasks (status=0) to queued (status=3).

    Returns the claimed ``(id, dataset_id)`` pairs, highest priority then
    oldest first (ties broken by id). dataset_id rides along into the message
    so the worker can prune its own lookup to one partition -- see
    _run_extract_task. Because the rows are claimed in the same statement
    that selects them, concurrent callers get disjoint sets: FOR UPDATE SKIP
    LOCKED steps past rows another transaction is claiming rather than
    waiting on them or handing out the same row twice. A queued row whose
    message never arrives (broker outage, worker killed mid-publish) is
    returned to pending by free_stale_processing_tasks.

    The `, id` tiebreaker matters at scale: build_extract_tasks inserts in
    large batches sharing one NOW() per INSERT, so many rows can carry the
    exact same (priority, submit_time). Without a deterministic tiebreaker,
    concurrent SKIP LOCKED scans have no stable order to partition across a
    large tied group -- every claimer effectively circles the same ambiguous
    block instead of cleanly dividing sequential work, and skip-distance
    grows with the tied-group size rather than just the concurrency level.
    `id` is already unique and monotonic, so it's a free, always-available
    tiebreaker -- see migration 0025, which adds it to
    extract_tasks_pending_idx so this ORDER BY can still be served by an
    index-only scan of the partial index rather than falling back to a sort.

    The id tiebreaker alone wasn't enough at production scale: run_extract_task
    self-chains (see its docstring below), so every worker slot calls this
    with limit=1 the instant it finishes a task. With ~150+ slots across the
    fleet, that's dozens of transactions concurrently racing FOR UPDATE SKIP
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

    Timed in two stages: waiting for the lock, and holding it through commit.
    The second is what the whole fleet queues behind, so its rate caps claims
    per second -- which is also why the claim commits asynchronously: a
    commit that waits for fsync holds the lock for the whole flush.
    """
    started = time.perf_counter()
    with transaction.atomic():
        with connection.cursor() as cursor:
            _execute_async(cursor, "SELECT pg_advisory_xact_lock(%s)", [CLAIM_LOCK_ID])
            locked = time.perf_counter()
            cursor.execute(
                """
                SELECT id, dataset_id FROM extract_tasks
                WHERE status = 0
                ORDER BY priority DESC, submit_time ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                [limit],
            )
            rows = cursor.fetchall()
            if rows:
                # dataset_id (the partition key) rides along so the UPDATE
                # below can prune to one partition per row instead of probing
                # all of them -- see the docstring above.
                values_clause = ", ".join(["(%s, %s)"] * len(rows))
                params = [
                    param for task_id, dataset_id in rows for param in (dataset_id, task_id)
                ]
                cursor.execute(
                    f"""
                    UPDATE extract_tasks AS t
                    SET status = 3, update_time = NOW()
                    FROM (VALUES {values_clause}) AS v(dataset_id, id)
                    WHERE t.dataset_id = v.dataset_id AND t.id = v.id
                    """,
                    params,
                )
    metrics.DISPATCH_SECONDS.labels("lock_wait").observe(locked - started)
    metrics.DISPATCH_SECONDS.labels("claim").observe(time.perf_counter() - locked)
    return rows


# Most tasks one claim statement may take, however large a limit the caller
# asks for. Two reasons, both reachable only from the beat's cold-start
# top-up (idle slots x batch size), never from the steady-state self-chain:
#
# The UPDATE builds one VALUES row per task, two bind parameters each, and
# PostgreSQL's limit is 65535 -- so a single claim of 32768+ tasks fails
# outright. At 384 slots and batch 64 the beat would already ask for 24576.
#
# And the claim runs under CLAIM_LOCK_ID, so the whole fleet waits on it. The
# SELECT merge-appends 56 partition indexes; asking for tens of thousands of
# rows in priority order turns a ~125ms hold into a multi-second one during
# exactly the cold start that rolling deploys create.
#
# Splitting costs an extra lock acquisition per chunk, which is only paid
# when filling a large number of idle slots at once.
_MAX_CLAIM_ROWS = 1024


def dispatch_pending_tasks(limit=None, batch_size=None):
    """Claim up to ``limit`` pending tasks and send them to the processing queue.

    ``limit`` counts tasks; they are published in messages of ``batch_size``
    tasks each, so this issues one claim (one advisory lock acquisition) for
    what used to take ``limit`` of them. Large limits are claimed in chunks of
    at most _MAX_CLAIM_ROWS. Returns the claimed ``(id, dataset_id)`` pairs,
    which are also what each message carries.
    """
    if batch_size is None:
        batch_size = _claim_batch_size()
    if limit is None:
        limit = batch_size

    claimed = []
    remaining = limit
    while remaining > 0:
        chunk = claim_pending_tasks(min(remaining, _MAX_CLAIM_ROWS))
        if not chunk:
            break
        claimed.extend(chunk)
        remaining -= len(chunk)

    if claimed:
        started = time.perf_counter()
        for start in range(0, len(claimed), batch_size):
            run_extract_task.delay(claimed[start : start + batch_size])
        metrics.DISPATCH_SECONDS.labels("publish").observe(time.perf_counter() - started)
    return claimed


# ignore_result: this is ~100% of the rows in django_celery_results_taskresult
# (measured in production, result rows tracked task messages 1:1 at ~775/min),
# and nothing reads them -- the self-chain drops its own return value and
# dispatch_processing_tasks sizes its top-up from worker introspection, not the
# result backend. Safe specifically because this task is never a chord member:
# the one chord in the codebase (sweep_coverage_records) has
# test_coverage_for_dataset as its header and build_extract_tasks as its body,
# and a chord is the one primitive that genuinely needs results to count
# completions. Do NOT set task_ignore_result globally for that reason.
@shared_task(ignore_result=True)
def run_extract_task(task_ids):
    """Run a batch of extract tasks by ID, then dispatch a replacement batch.

    Every exit path -- success, failure, or a no-op because a row was already
    taken -- chains into the next batch, so the worker slot stays busy without
    waiting for the dispatch_processing_tasks beat. Exactly one message is
    dispatched per message consumed, which is what keeps the fleet at steady
    state: the beat tops up to one in-flight message per slot, and a chain
    that fanned out would grow without bound.

    ``task_ids`` is a list of ``[id, dataset_id]`` pairs, as published by
    dispatch_pending_tasks. Older builds published plain ids, either as a
    list or as one bare id per message; those still run, just without the
    partition pruning that dataset_id buys (see _run_extract_task).
    """
    # A bare id arrives from any pod still running a build that published one
    # task per message. Harmless to keep permanently.
    #
    # The reverse direction is NOT safe: a pod from before pairs were
    # introduced cannot read a pair. Each task in such a message fails its
    # lookup and is logged, the chain still continues, and the rows stay
    # queued (status=3) until free_stale_processing_tasks returns them to
    # pending after STALE_TASK_MINUTES. So a rolling deploy across this
    # change delays some tasks; it does not lose them.
    if not isinstance(task_ids, (list, tuple)):
        task_ids = [task_ids]

    metrics.batch_started()
    results = []
    failures = []
    try:
        for ref in task_ids:
            task_id, dataset_id = ref if isinstance(ref, (list, tuple)) else (ref, None)
            try:
                results.append(_run_extract_task(task_id, dataset_id))
            except Exception as exc:
                # The rest of this batch is already claimed (status=3), so
                # letting the first failure abort the message would strand
                # them until free_stale_processing_tasks reaps them half an
                # hour later. Run them all, then surface the first failure so
                # the message is still recorded as failed.
                logger.exception("Extract task %s failed", task_id)
                failures.append(exc)
        if failures:
            raise failures[0]
        return results
    finally:
        try:
            dispatch_pending_tasks()
        except Exception:
            # Don't let a broker hiccup replace this batch's own outcome. The
            # beat bootstraps a replacement chain on its next tick.
            logger.exception("Tasks %s could not dispatch a successor", task_ids)
        # After the successor is published, so the idle gap this starts is
        # purely delivery: how long the slot waits for its next message.
        metrics.batch_finished()


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


def _run_extract_task(task_id, dataset_id=None):
    """Run one extract task, recording its outcome and per-phase timings.

    The timer is finished however _extract exits, so a raising task still
    counts toward throughput and charges its time to the phase that raised.
    """
    timer = metrics.TaskTimer(dataset_id)
    try:
        return _extract(task_id, dataset_id, timer)
    finally:
        timer.finish()


@dataclass(frozen=True)
class _ClaimedTask:
    dataset_id: int
    resource_ids: list[int]
    kwargs: dict | None
    function: str
    short_name: str
    po_kwargs: dict | None
    geometry_wkb: bytes


def _claim_extract_task(task_id, dataset_id=None):
    """Claim one task and return its inputs in a single autocommit statement.

    The materialized candidate locks only the task row, skipping a competing
    worker's lock. UPDATE RETURNING commits the claim before Python decodes
    the inputs, without holding a pooler connection across a SELECT/UPDATE
    round trip, and without waiting for fsync (see _execute_async). The
    PostGIS geometry is returned as WKB for Shapely directly.

    Name the partition on BOTH scans: a dataset_id join alone doesn't ensure
    the UPDATE prunes partitions. Legacy messages without dataset_id still
    work, but cannot get the same pruning (as with the old ORM lookup).
    """
    partition_filter = "AND t.dataset_id = %s" if dataset_id is not None else ""
    params = [task_id]
    if dataset_id is not None:
        params.extend([dataset_id, dataset_id])

    with connection.cursor() as cursor:
        _execute_async(
            cursor,
            f"""
            WITH candidate AS MATERIALIZED (
                SELECT t.id, t.dataset_id, t.resource_ids, t.kwargs,
                       po.function, po.short_name, po.kwargs AS po_kwargs,
                       ST_AsBinary(g.shape) AS geometry_wkb
                FROM extract_tasks AS t
                JOIN datasets AS d ON d.id = t.dataset_id
                JOIN processing_options AS po ON po.id = t.po_id
                JOIN feat_map AS fm ON fm.id = t.fm_id
                JOIN feature_collections AS fc ON fc.id = fm.fc_id
                JOIN features AS g ON g.id = fm.geom_id
                WHERE t.id = %s {partition_filter}
                  AND t.status IN (0, 3)
                  AND d.active AND po.active AND fc.active
                LIMIT 1
                FOR UPDATE OF t SKIP LOCKED
            )
            UPDATE extract_tasks AS t
            SET status = 2, update_time = statement_timestamp()
            FROM candidate
            WHERE t.dataset_id = candidate.dataset_id AND t.id = candidate.id
              {partition_filter}
            RETURNING candidate.dataset_id, candidate.resource_ids,
                      candidate.kwargs::text, candidate.function,
                      candidate.short_name, candidate.po_kwargs::text,
                      candidate.geometry_wkb
            """,
            params,
        )
        row = cursor.fetchone()

    if row is None:
        return None
    dataset_id, resource_ids, kwargs, function, short_name, po_kwargs, wkb = row
    return _ClaimedTask(
        dataset_id=dataset_id,
        resource_ids=resource_ids,
        kwargs=json.loads(kwargs) if kwargs is not None else None,
        function=function,
        short_name=short_name,
        po_kwargs=json.loads(po_kwargs) if po_kwargs is not None else None,
        geometry_wkb=bytes(wkb),
    )


def _extract(task_id, dataset_id, timer):
    """Lock the task row, run the processor once per resource, and store results.

    Accepts rows in pending (0) or queued (3). On success (no position raised
    this run) status is set to 1; otherwise -1 with a summary of what failed.
    A NULL value is nodata, a final answer, and does not hold a task back.
    Each resource_ids[i] is processed independently -- one
    resource's exception is caught and leaves that position NULL rather than
    aborting the others in the same run (see the per-resource try/except
    below) or failing the task outright (see the conditional re-raise at the
    bottom).

    ``dataset_id`` is the task's partition key, carried in the message from
    the claim. None is accepted for messages published by older builds; the
    lookup still works, it just can't prune.
    """
    logger.info("Running extract task %s", task_id)

    task = _claim_extract_task(task_id, dataset_id)
    if task is None:
        logger.info(
            "Task %s is not available (already locked, done, or filtered out)",
            task_id,
        )
        timer.outcome = "unavailable"
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
        # dataset by construction (see build_extract_tasks.py's equivalent
        # resource_ids[1] comment), so any one of them stands in for it.
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

            op_kwargs = {"name": task.short_name}
            if task.po_kwargs:
                op_kwargs.update(task.po_kwargs)
            if task.kwargs:
                op_kwargs.update(task.kwargs)
                kwargs_hash = hashlib.md5(
                    json.dumps(task.kwargs, sort_keys=True).encode()
                ).hexdigest()[:8]
                op_kwargs["name"] = f"{task.short_name}_{kwargs_hash}"

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
        # here, indistinguishable from nodata at the row level. Two consumers,
        # two different reasons that is acceptable:
        #   - merge (the CSV download path) gates on status=1, so a failed
        #     task's rows are never merged at all.
        #   - visualize does NOT gate on status -- neither the request nor the
        #     explore SQL filters et.status -- but a failed position already
        #     rendered as an empty cell there before this change, so nothing
        #     regresses.
        # What broadens is the MEANING of an empty cell, from "failed or not
        # yet processed" to "failed or nodata". Both render identically.
        rows = []
        for name, values_by_pos in produced.items():
            row = ExtractData(
                extract_task_id=task_id,
                dataset_id=task.dataset_id,
                name=name,
            )
            column = _column_for(values_by_pos)
            if column is not None:
                if n == 1:
                    classified = _classify_value(values_by_pos.get(0))
                    if classified is not None:
                        setattr(row, f"{column}_value", classified[1])
                else:
                    values = [None] * n
                    for i, value in values_by_pos.items():
                        classified = _classify_value(value)
                        if classified is not None:
                            if classified[0] != column:
                                logger.warning(
                                    "Task %s name %s position %d: %s value in a %s "
                                    "row. Stored as-is; a genuinely incompatible type "
                                    "will raise at insert. A name is assumed to "
                                    "produce one type across every position.",
                                    task_id, name, i, classified[0], column,
                                )
                            values[i] = classified[1]
                    setattr(row, f"{column}_values", values)
            rows.append(row)

        # The delete is guarded on `produced` being non-empty: an empty one
        # means EVERY position raised this run, and wiping a previous run's
        # good results because of a transient failure would be strictly worse
        # than keeping them. The task goes to status=-1 either way and is
        # recomputed in full on retry. The old merge-based code got this for
        # free via its `elif not values_by_pos: continue` branch. dataset_id
        # prunes the delete to one partition.
        #
        # delete + bulk_create have to land together: a crash between them
        # would leave the task with no rows at all and nothing written back.
        # Rows are built above, outside this block, so it holds no locks while
        # doing Python work. The delete and insert are ORM calls with nothing
        # to prefix, so the async commit (see _execute_async) costs this one
        # statement.
        with transaction.atomic():
            if not _synchronous_commit():
                with connection.cursor() as cursor:
                    cursor.execute(_ASYNC_COMMIT)
            if produced:
                ExtractData.objects.filter(
                    dataset_id=task.dataset_id, extract_task_id=task_id
                ).delete()
            ExtractData.objects.bulk_create(rows)
        all_names = set(produced)

    except Exception as exc:
        logger.exception("Task %s failed: %s", task_id, exc)
        timer.enter("finalize")
        # dataset_id included so this prunes to one partition instead of
        # scanning all of them.
        ExtractTask.objects.filter(id=task_id, dataset_id=task.dataset_id).update(
            status=-1, error=repr(exc)[:100]
        )
        timer.outcome = "failed"
        raise

    timer.enter("finalize")
    # A run that raised nothing is complete. A NULL value means the extraction
    # ran and found nodata -- a final answer, not an unfinished position (see
    # _positions_needing_processing).
    incomplete_positions = {i for _, i, _ in failures}

    if not incomplete_positions:
        # dataset_id included so this prunes to one partition. The database
        # clock, like update_time in the claim, so durations never mix a
        # worker's clock with the primary's. Raw SQL rather than the ORM so
        # the async commit rides in the same round trip.
        with connection.cursor() as cursor:
            _execute_async(
                cursor,
                "UPDATE extract_tasks SET status = 1, complete_time = statement_timestamp() "
                "WHERE dataset_id = %s AND id = %s",
                [task.dataset_id, task_id],
            )
        timer.outcome = "completed"
        logger.info("Task %s completed", task_id)
        return {"task_id": task_id, "results": len(all_names)}

    parts = [f"resource {rid}[{i}]: {exc!r}" for rid, i, exc in failures]
    error = "; ".join(parts)[:100]
    ExtractTask.objects.filter(id=task_id, dataset_id=task.dataset_id).update(
        status=-1, error=error
    )
    timer.outcome = "failed"
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
