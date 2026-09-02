import hashlib
import json
import logging
from pathlib import Path
from warnings import catch_warnings

import shapely
from celery import shared_task
from django.db import connection, transaction
from django.utils import timezone

from analytics.models import ExtractTask

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


def _store_extract_value(extract_task_id, name, value):
    """Insert a single result row into extract_data."""
    if isinstance(value, int):
        data_column, float_val, int_val, str_val = "int", None, value, None
    elif isinstance(value, float):
        data_column, float_val, int_val, str_val = "float", value, None, None
    elif isinstance(value, str):
        data_column, float_val, int_val, str_val = "str", None, None, value
    else:
        data_column, float_val, int_val, str_val = "str", None, None, str(value)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO extract_data
                (extract_task_id, name, data_column, float_value, int_value, str_value)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [extract_task_id, name, data_column, float_val, int_val, str_val],
        )


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


def _run_extract_task(task_id):
    """Lock the task row, run the processor, and store the results.

    Accepts rows in pending (0) or queued (3). On success the status is set
    to 1; on failure it is set to -1 with the error message recorded.
    """
    logger.info("Running extract task %s", task_id)
    now = timezone.now

    with transaction.atomic():
        task = (
            ExtractTask.objects.select_for_update(of=("self",), skip_locked=True)
            .select_related("resource__dataset", "po", "fm__fc", "fm__geom")
            .filter(
                id=task_id,
                status__in=(0, 3),
                fm__fc__active=True,
                resource__dataset__active=True,
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

    # Everything from here through result storage can raise; catch all of it so
    # the task is marked -1 rather than left stranded at status=2.
    try:
        dataset = task.resource.dataset
        dataset_path = Path(dataset.path) / task.resource.path
        func = get_func(task.po.function)

        geometry = shapely.from_wkb(bytes(task.fm.geom.shape.wkb))

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

        with catch_warnings(record=True) as warnings:
            results = func(geometry, dataset_path, **op_kwargs)
            for w in warnings:
                logger.warning("Warning in task %s: %s", task_id, w.message)

        # Store results and mark complete
        with connection.cursor() as cursor:
            for name, value in results:
                _store_extract_value(task_id, name, value)
            cursor.execute(
                "UPDATE extract_tasks SET status = 1, complete_time = %s WHERE id = %s",
                [now(), task_id],
            )

        logger.info("Task %s completed with %d result(s)", task_id, len(results))
        return {"task_id": task_id, "results": len(results)}

    except Exception as exc:
        logger.exception("Task %s failed: %s", task_id, exc)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE extract_tasks SET status = -1, error = %s WHERE id = %s",
                [repr(exc)[:100], task_id],
            )
        raise
