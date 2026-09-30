import hashlib
import json
import logging
from pathlib import Path
from warnings import catch_warnings

import shapely
from celery import shared_task
from django.db import connection, transaction
from django.utils import timezone

from analytics.models import ExtractData, ExtractTask
from datasets.models import Dataset, DatasetResource

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


def claim_pending_tasks(limit=1):
    """Move up to ``limit`` pending tasks (status=0) to queued (status=3).

    Returns the claimed ids, highest priority then oldest first (ties broken
    by id). Because the rows are claimed in the same statement that selects
    them, concurrent callers get disjoint sets: FOR UPDATE SKIP LOCKED steps
    past rows another transaction is claiming rather than waiting on them or
    handing out the same row twice. A queued row whose message never arrives
    (broker outage, worker killed mid-publish) is returned to pending by
    free_stale_processing_tasks.

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
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [CLAIM_LOCK_ID])
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
            if not rows:
                return []

            # dataset_id (the partition key) rides along so the UPDATE below
            # can prune to one partition per row instead of probing all of
            # them -- see the docstring above.
            ids = [task_id for task_id, _ in rows]
            values_clause = ", ".join(["(%s, %s)"] * len(rows))
            params = [param for task_id, dataset_id in rows for param in (dataset_id, task_id)]
            cursor.execute(
                f"""
                UPDATE extract_tasks AS t
                SET status = 3, update_time = NOW()
                FROM (VALUES {values_clause}) AS v(dataset_id, id)
                WHERE t.dataset_id = v.dataset_id AND t.id = v.id
                """,
                params,
            )
            return ids


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
    at most _MAX_CLAIM_ROWS. Returns the claimed task ids.
    """
    if batch_size is None:
        batch_size = _claim_batch_size()
    if limit is None:
        limit = batch_size

    task_ids = []
    remaining = limit
    while remaining > 0:
        chunk = claim_pending_tasks(min(remaining, _MAX_CLAIM_ROWS))
        if not chunk:
            break
        task_ids.extend(chunk)
        remaining -= len(chunk)

    for start in range(0, len(task_ids), batch_size):
        run_extract_task.delay(task_ids[start : start + batch_size])
    return task_ids


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
    """
    # A bare id arrives from any pod still running a build that published one
    # task per message. Harmless to keep permanently, and it is what makes a
    # rolling deploy safe in both directions.
    if not isinstance(task_ids, (list, tuple)):
        task_ids = [task_ids]

    results = []
    failures = []
    try:
        for task_id in task_ids:
            try:
                results.append(_run_extract_task(task_id))
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


def _run_extract_task(task_id):
    """Lock the task row, run the processor once per resource, and store results.

    Accepts rows in pending (0) or queued (3). On success (no position raised
    this run) status is set to 1; otherwise -1 with a summary of what failed.
    A NULL value is nodata, a final answer, and does not hold a task back.
    Each resource_ids[i] is processed independently -- one
    resource's exception is caught and leaves that position NULL rather than
    aborting the others in the same run (see the per-resource try/except
    below) or failing the task outright (see the conditional re-raise at the
    bottom).
    """
    logger.info("Running extract task %s", task_id)
    now = timezone.now

    with transaction.atomic():
        task = (
            ExtractTask.objects.select_for_update(of=("self",), skip_locked=True)
            .select_related("po", "fm__fc", "fm__geom")
            .filter(
                id=task_id,
                status__in=(0, 3),
                fm__fc__active=True,
                dataset_id__in=Dataset.objects.filter(active=True).values("id"),
                po__active=True,
            )
            .first()
        )

        if task is None:
            logger.info(
                "Task %s is not available (already locked, done, or filtered out)",
                task_id,
            )
            return None

        task.status = 2
        task.update_time = now()
        # Explicit filter, not task.save() -- save() would only filter by id,
        # and (like claim_pending_tasks before it) an UPDATE without the
        # dataset_id partition key doesn't get the same per-partition index
        # seek a SELECT does: it falls back to a full local-index scan on
        # every partition. Confirmed via EXPLAIN ANALYZE against production:
        # a bare `WHERE id = X` update took 3.2s; adding dataset_id dropped
        # it to sub-millisecond.
        ExtractTask.objects.filter(id=task_id, dataset_id=task.dataset_id).update(
            status=2, update_time=task.update_time
        )

    # Setup (resolving resources/func/geometry) and the merge-into-ExtractData
    # step can both raise unexpectedly; catch that the same way the old code
    # did, marking -1 with repr(exc) and re-raising. Per-resource processing
    # failures are handled separately inside the loop below and never reach
    # this except -- they're expected, not exceptional.
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
        func = get_func(task.po.function)

        geometry = shapely.from_wkb(bytes(task.fm.geom.shape.wkb))

        n = len(task.resource_ids)
        positions = _positions_needing_processing(n)

        # name -> {position: value}, accumulated only from calls that
        # succeeded this run. A resource whose call raises contributes
        # nothing here, so its position stays/becomes NULL in every name's
        # array below rather than blocking the other positions.
        produced = {}
        failures = []  # (resource_id, position, exc) for each call that raised this run

        for i in sorted(positions):
            resource = resources[i]
            dataset_path = Path(dataset.path) / resource.path

            op_kwargs = {"name": task.po.short_name}
            if task.po.kwargs:
                op_kwargs.update(task.po.kwargs)
            if task.kwargs:
                op_kwargs.update(task.kwargs)
                kwargs_hash = hashlib.md5(
                    json.dumps(task.kwargs, sort_keys=True).encode()
                ).hexdigest()[:8]
                op_kwargs["name"] = f"{task.po.short_name}_{kwargs_hash}"

            if dataset.mapped:
                op_kwargs["category_map"] = dict(
                    dataset.mappings.values_list("map_val", "map_name")
                )

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
        # doing Python work.
        with transaction.atomic():
            if produced:
                ExtractData.objects.filter(
                    dataset_id=task.dataset_id, extract_task_id=task_id
                ).delete()
            ExtractData.objects.bulk_create(rows)
        all_names = set(produced)

    except Exception as exc:
        logger.exception("Task %s failed: %s", task_id, exc)
        # dataset_id included so this prunes to one partition instead of
        # scanning all of them -- see the status=2 update above.
        ExtractTask.objects.filter(id=task_id, dataset_id=task.dataset_id).update(
            status=-1, error=repr(exc)[:100]
        )
        raise

    # A run that raised nothing is complete. A NULL value means the extraction
    # ran and found nodata -- a final answer, not an unfinished position (see
    # _positions_needing_processing).
    incomplete_positions = {i for _, i, _ in failures}

    if not incomplete_positions:
        # dataset_id included so this prunes to one partition -- see the
        # status=2 update earlier in this function.
        ExtractTask.objects.filter(id=task_id, dataset_id=task.dataset_id).update(
            status=1, complete_time=now()
        )
        logger.info("Task %s completed", task_id)
        return {"task_id": task_id, "results": len(all_names)}

    parts = [f"resource {rid}[{i}]: {exc!r}" for rid, i, exc in failures]
    error = "; ".join(parts)[:100]
    ExtractTask.objects.filter(id=task_id, dataset_id=task.dataset_id).update(
        status=-1, error=error
    )
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
