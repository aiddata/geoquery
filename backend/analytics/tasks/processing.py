import logging
from pathlib import Path
from warnings import catch_warnings

import shapely
from celery import shared_task
from django.db import connection
from django.utils import timezone

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

    with connection.cursor() as cursor:
        # Lock and fetch the task together with all related data in one query.
        cursor.execute(
            """
            SELECT
                et.id AS task_id,
                d.id AS dataset_id,
                d.path AS dataset_path,
                d.mapped AS mapped_dataset,
                dr.path AS resource_path,
                po.function AS po_func,
                po.short_name AS po_short_name,
                po.kwargs AS po_kwargs,
                f.shape AS feature
            FROM extract_tasks et
            JOIN feat_map fm ON fm.id = et.fm_id
            JOIN features f ON f.id = fm.geom_id
            JOIN feature_collections fc ON fc.id = fm.fc_id
            JOIN dataset_resources dr ON dr.id = et.resource_id
            JOIN datasets d ON d.id = dr.dataset_id
            JOIN processing_options po ON po.id = et.po_id
            WHERE et.id = %s
              AND et.status = 0
              AND fc.active
              AND d.active
              AND po.active
            FOR UPDATE OF et SKIP LOCKED
            """,
            [task_id],
        )
        row = cursor.fetchone()

        if row is None:
            logger.info("Task %s is not available (already locked, done, or filtered out)", task_id)
            return None

        (
            _task_id, dataset_id, dataset_path, mapped_dataset,
            resource_path, po_func, po_short_name, po_kwargs, feature_wkb,
        ) = row

        # Mark as locked
        cursor.execute(
            "UPDATE extract_tasks SET status = 2, update_time = %s WHERE id = %s",
            [now(), task_id],
        )

    # Prepare inputs outside the lock
    raster_path = Path(dataset_path) / resource_path
    func = get_func(po_func)
    geometry = shapely.wkb.loads(bytes(feature_wkb))

    op_kwargs = {"name": po_short_name}
    if po_kwargs:
        op_kwargs.update(po_kwargs)

    if mapped_dataset:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT map_val, map_name FROM mappings WHERE dataset_id = %s",
                [dataset_id],
            )
            op_kwargs["category_map"] = {r[0]: r[1] for r in cursor.fetchall()}

    # Execute the processor function
    try:
        with catch_warnings(record=True) as warnings:
            results = func(geometry, raster_path, **op_kwargs)
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
