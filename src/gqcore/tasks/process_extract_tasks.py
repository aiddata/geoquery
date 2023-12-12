import builtins
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Tuple

from dask.distributed import Client, LocalCluster, wait
from loguru import logger
from shapely import Geometry

import gqcore.utils.processors
from gqcore.utils.db.extract_task_processing import (
    ExtractData,
    ExtractTaskToRun,
    LockTask,
    NoTaskAvailableError,
    count_available_tasks,
    get_mappings,
)
from gqcore.utils.logs import add_handler


def get_func(op: str) -> Callable:
    """Get appropriate function for operation."""
    if hasattr(gqcore.utils.processors, op):
        func = getattr(gqcore.utils.processors, op)
    else:
        raise ValueError(f"Operation {op} not supported.")
    return func


def run_task(
    func: Callable, task_id: int, feat: Geometry, data: Any, op_kwargs
) -> List[ExtractData]:
    result = func(feat, data, **op_kwargs)

    return [
        ExtractData(
            id=task_id,
            name=method,
            value=val,
        )
        for method, val in result
    ]


def prepare_task(data: ExtractTaskToRun) -> Tuple[Callable, int, Geometry, Any, Dict]:
    path = Path(data.dataset_path) / data.resource_path
    func = get_func(data.po_func)
    op_kwargs = {"name": data.po_short_name}
    if data.mappings:
        op_kwargs["category_map"] = {i["map_val"]: i["map_name"] for i in data.mappings}
    op_kwargs.update(data.po_kwargs)
    return (func, data.id, data.feature, path, op_kwargs)


def task_generator() -> Iterator[LockTask]:
    try:
        with LockTask() as task:
            yield task
    except NoTaskAvailableError:
        return


def process_tasks_sequentially() -> None:
    for task in task_generator():
        for result in run_task(*prepare_task(task.data)):
            task.submit_result(result)


def run_one_task(*args) -> None:
    try:
        with LockTask() as task:
            for result in run_task(*prepare_task(task.data)):
                task.submit_result(result)
    except NoTaskAvailableError:
        return


def process_tasks_concurrently(max_workers: int = 10, max_tasks=10000) -> None:
    tasks_available: int = count_available_tasks()
    if tasks_available < max_tasks:
        run_count = tasks_available
    else:
        run_count = tasks_available

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for i in range(run_count):
            executor.submit(run_one_task)


def process_tasks_using_dask(max_tasks=10000) -> None:
    tasks_available: int = count_available_tasks()
    logger.debug(f"{tasks_available} tasks available in queue")
    if tasks_available > 0:
        if tasks_available < max_tasks:
            run_count = tasks_available
        else:
            run_count = tasks_available

        logger.info("Starting local dask cluster")
        cluster = LocalCluster(n_workers=16)
        client = Client(cluster)
        logger.info(f"Link to Dask dashboard: {cluster.dashboard_link}")

        logger.info(f"Submitting {run_count} jobs to the dask cluster.")
        futures = client.map(run_one_task, range(run_count))

        wait(futures)


if __name__ == "__main__":
    add_handler("process_extract_tasks")
    process_tasks_using_dask()
