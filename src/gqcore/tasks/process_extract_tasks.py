import builtins
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, Callable, Dict, Iterator, List, Tuple

from shapely import Geometry

import gqcore.utils.processors
from gqcore.utils.db.extract_task_processing import (
    ExtractData,
    ExtractTaskToRun,
    LockTask,
    NoTaskAvailableError,
    get_mappings,
)


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


def run_one_task() -> None:
    try:
        with LockTask() as task:
            for result in run_task(*prepare_task(task.data)):
                task.submit_result(result)
    except NoTaskAvailableError:
        return


def process_tasks_concurrently(max_workers: int = 10) -> None:
    with ProcessPoolExecutor(max_workers = max_workers) as executor:
        for i in range(1000):
            executor.submit(run_one_task)

    """
    with Pool(processes=max_workers) as pool:
        with ExitStack() as stack:
            task_results: List[Tuple[LockTask, AsyncResult]] = []
            while True:
                # submit any completed results
                for i, task_result in enumerate(task_results):
                    if task_result[1].ready():
                        task, results = task_results.pop(i)
                        for result in results.get():
                            task.submit_result(result)
                        task.__exit__(None, None, None)

                # if queued tasks have completed, submit their results
                # if the queue needs new tasks, add one
                if pool._taskqueue.empty():
                    try:
                        # is there another task available?
                        task = next(task_generator())
                        # have our ExitStack exit the task context later
                        stack.push(task)
                    except StopIteration:
                        # there was not another task available
                        pass
                    else:
                        # there was another task available
                        run_task_args = prepare_task(task.data)
                        # submit task to pool
                        results_future = pool.apply_async(run_task, run_task_args)
                        # add task and its future to task_results
                        task_results.append((task, results_future))

                # are there no result futures in our list anymore?
                # this means there is nothing more to do
                if len(task_results) == 0:
                    break

                sleep(0.5)
    """


if __name__ == "__main__":
    process_tasks_concurrently()
    # process_tasks_sequentially()
