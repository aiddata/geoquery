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


# Processor function registry — mirrors gqcore.utils.processors
PROCESSOR_FUNCTIONS = {}


def _import_processors():
    """Lazily import processor functions from gqcore.utils.processors."""
    global PROCESSOR_FUNCTIONS
    if PROCESSOR_FUNCTIONS:
        return
    import gqcore.utils.processors as proc_module

    for name in dir(proc_module):
        obj = getattr(proc_module, name)
        if callable(obj) and not name.startswith("_"):
            PROCESSOR_FUNCTIONS[name] = obj


def get_func(op):
    """Get the processor function for the given operation name."""
    _import_processors()
    func = PROCESSOR_FUNCTIONS.get(op)
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


@shared_task
def run_extract_task(task_id):
    """Run a single extract task by ID.

    Locks the task row (SELECT ... FOR UPDATE SKIP LOCKED), executes the
    processor function against the feature geometry and raster resource,
    then stores results.  On success the task status is set to 1; on
    failure it is set to -1 with the error message recorded.
    """
    logger.info("Running extract task %s", task_id)
    now = timezone.now

    with transaction.atomic():
        task = (
            ExtractTask.objects.select_for_update(of=("self",), skip_locked=True)
            .select_related("resource__dataset", "po", "fm__fc", "fm__geom")
            .filter(
                id=task_id,
                status=0,
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

    # Execute the processor function
    try:
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
