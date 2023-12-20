import builtins
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Tuple
from warnings import catch_warnings
from collections import OrderedDict


from dask_kubernetes.operator import KubeCluster
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
from gqcore.utils.logs import get_logger


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
    # this re-import is necessary if this is running on a dask worker
    from loguru import logger

    logger.info(f"Running task with id {task_id}...")

    with catch_warnings(record=True) as warnings:
        result = func(feat, data, **op_kwargs)
        for warning in warnings:
            logger.warning(
                f"Warning caught while running task {task_id}: {warning.message}"
            )

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
        while True:
            with LockTask() as task:
                yield task
    except NoTaskAvailableError:
        return


@logger.catch(reraise=True)
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


@logger.catch(reraise=True)
def process_tasks_concurrently(max_workers: int = 10, max_tasks=10000) -> None:
    tasks_available: int = count_available_tasks()
    logger.debug(f"{tasks_available} tasks available in queue")
    if tasks_available < max_tasks:
        run_count = tasks_available
    else:
        run_count = tasks_available

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for i in range(run_count):
            executor.submit(run_one_task)


@logger.catch(reraise=True)
def process_tasks_using_dask(max_tasks=10000) -> None:
    tasks_available: int = count_available_tasks()
    logger.debug(f"{tasks_available} tasks available in queue")
    if tasks_available > 0:
        if tasks_available < max_tasks:
            run_count = tasks_available
        else:
            run_count = tasks_available

        # logger.info("Starting local dask cluster")
        # cluster = LocalCluster(n_workers=16)
        # client = Client(cluster)

        logger.info("Connecting to k8s dask cluster (KubeCluster)")
        cluster = KubeCluster.from_name("extract-dask-cluster")
        client = Client(cluster)

        logger.info(f"Link to Dask dashboard: {cluster.dashboard_link}")

        logger.info(f"Submitting {run_count} jobs to the dask cluster.")
        futures = client.map(run_one_task, range(run_count))

        wait(futures)
        logger.info(f"Finished processing {run_count} jobs")


def manage_task_processing_for_k8s(max_tasks=10000, max_workers=100, active_sleep=5, inactive_sleep=30, scale_dict=None) -> None:

    if max_workers % 2 != 0:
        logger.warning(f"max_workers ({max_workers}) should be an even number, but is not, reducing by 1")
        max_workers -= 1

    if scale_dict is None:
        scale_dict = {
            # 10000000: 20,
            # 10000: 10,
            # 100: 5,
            # 10: 2,
            1: max_workers,
        }

    # sort scale_dict by key
    scale_dict = OrderedDict(scale_dict)
    scale_dict = OrderedDict(sorted(scale_dict.items(), key=lambda t: t[0]))

    logger.info(f"Preparing to run extract tasks using dask on k8s cluster")

    cluster = KubeCluster.from_name("extract-dask-cluster")
    client = Client(cluster)

    while True:
        current_scale = len(client.scheduler_info()['workers'])

        tasks_available = count_available_tasks()

        if tasks_available == 0:
            if current_scale > 1:
                logger.debug(f"No tasks available, but {current_scale} workers running, scaling down to 1")
                cluster.scale(1)
            time.sleep(inactive_sleep)

        else:
            logger.debug(f"{tasks_available} tasks available in queue")
            for threshold, scale in scale_dict.items():
                if tasks_available > threshold:
                    if current_scale % 2 == 0:
                        cluster.scale(scale)
                    else:
                        logger.debug(f"Current scale is {current_scale}, not scaling to {scale}")
                        continue

            process_tasks_using_dask(max_tasks=max_tasks)

            time.sleep(active_sleep)


if __name__ == "__main__":
    get_logger("process_extract_tasks")
    manage_task_processing_for_k8s()
