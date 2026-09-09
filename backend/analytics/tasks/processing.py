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
    """Return (data_column, coerced_value) for a raw processor result.

    Matches the old scalar _store_extract_value's type dispatch: int before
    float (order matters -- bool would otherwise be misfiled as int, but
    processors never return bool here so it's not a live concern), anything
    that isn't int/float/str is stringified rather than dropped.
    """
    if isinstance(value, int):
        return "int", value
    elif isinstance(value, float):
        return "float", value
    elif isinstance(value, str):
        return "str", value
    else:
        return "str", str(value)


def claim_pending_tasks(limit=1):
    """Move up to ``limit`` pending tasks (status=0) to queued (status=3).

    Returns the claimed ids, highest priority then oldest first. Because the
    rows are claimed in the same statement that selects them, concurrent
    callers get disjoint sets: FOR UPDATE SKIP LOCKED steps past rows another
    transaction is claiming rather than waiting on them or handing out the
    same row twice. A queued row whose message never arrives (broker outage,
    worker killed mid-publish) is returned to pending by
    free_stale_processing_tasks.
    """
    # RETURNING gives no ordering guarantee, so re-sort the (at most `limit`)
    # claimed rows: the beat dispatches its batch in the order returned here.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH claimed AS (
                UPDATE extract_tasks
                SET status = 3, update_time = NOW()
                WHERE id IN (
                    SELECT id FROM extract_tasks
                    WHERE status = 0
                    ORDER BY priority DESC, submit_time ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                RETURNING id, priority, submit_time
            )
            SELECT id FROM claimed ORDER BY priority DESC, submit_time ASC
            """,
            [limit],
        )
        return [row[0] for row in cursor.fetchall()]


def dispatch_pending_tasks(limit=1):
    """Claim up to ``limit`` pending tasks and send each to the processing queue."""
    task_ids = claim_pending_tasks(limit)
    for task_id in task_ids:
        run_extract_task.delay(task_id)
    return task_ids


@shared_task
def run_extract_task(task_id):
    """Run a single extract task by ID, then dispatch the next pending one.

    Every exit path -- success, failure, or a no-op because the row was
    already taken -- chains into the next task, so the worker slot stays busy
    without waiting for the dispatch_processing_tasks beat.
    """
    try:
        return _run_extract_task(task_id)
    finally:
        try:
            dispatch_pending_tasks(1)
        except Exception:
            # Don't let a broker hiccup replace this task's own outcome. The
            # beat bootstraps a replacement chain on its next tick.
            logger.exception("Task %s could not dispatch a successor", task_id)


def _positions_needing_processing(n, existing_rows):
    """Which indices into resource_ids (0..n-1) still need a value computed.

    First run (no ExtractData rows yet): every position. On a rerun, a
    position needs (re)processing if ANY existing row has a NULL at that
    index in whichever array field matches its data_column. Granularity here
    is per resource-index, not per name: a single processor call for one
    resource typically returns several named results at once (e.g. mean,
    min, max), so if even one of those names is still NULL at position i,
    the whole call for resource i has to be redone -- there's no way to
    recompute just the missing name. Positions where every name is already
    filled are left out entirely, which is what makes a rerun skip a
    previously-successful resource instead of recomputing it.
    """
    if not existing_rows:
        return set(range(n))

    positions = set()
    for row in existing_rows:
        values = getattr(row, f"{row.data_column}_values") or []
        for i in range(n):
            if i >= len(values) or values[i] is None:
                positions.add(i)
    return positions


def _run_extract_task(task_id):
    """Lock the task row, run the processor once per resource, and store results.

    Accepts rows in pending (0) or queued (3). On success (every position of
    every name filled) status is set to 1; otherwise -1 with a summary of
    what failed. Each resource_ids[i] is processed independently -- one
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
        task.save(update_fields=["status", "update_time"])

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
        existing_rows = list(ExtractData.objects.filter(extract_task_id=task_id))
        positions = _positions_needing_processing(n, existing_rows)

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

        existing_by_name = {row.name: row for row in existing_rows}
        # The set of distinct result names across both prior runs and this
        # one -- reused below for the reported `results` count so it stays
        # the actual number of names rather than double-counting a name that
        # exists in both existing_by_name and produced (e.g. a rerun that
        # fills a previously-NULL position for a name already partially
        # filled by an earlier run).
        all_names = set(existing_by_name) | set(produced)
        for name in all_names:
            values_by_pos = produced.get(name, {})
            row = existing_by_name.get(name)

            if row is None:
                # First time this name has appeared for this task; seed a
                # fresh row with a fully-NULL array and fill in only the
                # positions this run actually produced.
                data_column, _ = _classify_value(next(iter(values_by_pos.values())))
                row = ExtractData(
                    extract_task_id=task_id,
                    dataset_id=task.dataset_id,
                    name=name,
                    data_column=data_column,
                )
                setattr(row, f"{data_column}_values", [None] * n)
            elif not values_by_pos:
                # Nothing new for this already-existing name this run --
                # leave every position (filled or still-NULL) untouched.
                continue

            # data_column is fixed at row creation (above) and assumed to be
            # valid for every future value stored under this name -- i.e. a
            # given name is assumed to always produce the same value type
            # across every position and every run. If a name ever produced a
            # mixed type (e.g. int on one call, str on another), the value
            # would still be coerced and stored into the array chosen by the
            # *first* type seen, silently misfiling it rather than raising.
            array_field = f"{row.data_column}_values"
            values = list(getattr(row, array_field) or [None] * n)
            values += [None] * (n - len(values))
            for i, value in values_by_pos.items():
                _, coerced = _classify_value(value)
                values[i] = coerced
            setattr(row, array_field, values)
            row.save()

    except Exception as exc:
        logger.exception("Task %s failed: %s", task_id, exc)
        ExtractTask.objects.filter(id=task_id).update(
            status=-1, error=repr(exc)[:100]
        )
        raise

    # A position is incomplete if either (a) it raised this run -- an empty
    # result list is a legitimate success and must NOT be confused with a
    # position that has no ExtractData row because it failed, or (b) some
    # name's stored array still has a NULL there, which also catches a name
    # that finished filling on an EARLIER run without this run touching it.
    failed_positions = {i for _, i, _ in failures}
    null_positions = set()
    for row in ExtractData.objects.filter(extract_task_id=task_id):
        values = list(getattr(row, f"{row.data_column}_values") or [])
        values += [None] * (n - len(values))
        null_positions.update(i for i in range(n) if values[i] is None)

    incomplete_positions = failed_positions | null_positions

    if not incomplete_positions:
        ExtractTask.objects.filter(id=task_id).update(status=1, complete_time=now())
        logger.info("Task %s completed", task_id)
        return {"task_id": task_id, "results": len(all_names)}

    parts = [f"resource {rid}[{i}]: {exc!r}" for rid, i, exc in failures]
    if null_positions - failed_positions:
        parts.append(f"positions still null: {sorted(null_positions - failed_positions)}")
    error = "; ".join(parts)[:100]
    ExtractTask.objects.filter(id=task_id).update(status=-1, error=error)
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
