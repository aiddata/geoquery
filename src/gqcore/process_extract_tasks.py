import builtins
from contextlib import ExitStack
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Tuple

from shapely import Geometry
from utils.db.extract_task_processing import (
    ExtractData,
    ExtractTaskToRun,
    LockTask,
    get_mappings,
)

import utils.processors


def get_func(op: str) -> Callable:
    """Get appropriate function for operation."""
    if hasattr(utils.processors, op):
        func = getattr(utils.processors, op)
    else:
        raise ValueError(f"Operation {op} not supported.")
    return func


def run_task(
    func: Callable, task_id: int, feat: Geometry, data: Any, op_kwargs
) -> Iterator[ExtractData]:
    result = func(feat, data, **op_kwargs)

    for method, val in result:
        yield ExtractData(
            id=task_id,
            name=method,
            value=val,
        )


def prepare_task(data: ExtractTaskToRun) -> Tuple[Callable, int, Geometry, Any, Dict]:
    path = Path(data.dataset_path) / data.resource_path
    func = get_func(data.po_func)
    op_kwargs = {"stat": data.po_short_name}
    if data.mappings:
        op_kwargs["category_map"] = {i["map_val"]: i["map_name"] for i in data.mappings}

    return (func, data.id, data.feature, path, op_kwargs)


def task_generator() -> Iterator[LockTask]:
    with LockTask() as task:
        if task.found_task():
            yield task
        else:
            raise StopIteration("No available tasks in queue.")


def process_tasks_sequentially() -> None:
    for task in task_generator():
        for result in run_task(*prepare_task(task.data)):
            task.submit_result(result)


"""
def process_tasks_concurrently(max_workers: int=5) -> None:
    with Pool(processes=max_workers) as pool:
        # add max_size limit to the queue?
        breakpoint()
        with ExitStack() as stack:
            for task in task_generator():
                # push task's __exit__ function onto ExitStack
                stack.push(task)

                # 

            
            # this doesn't work, unfortunately.
            # I think I need to find a new approach to generating
            # available tasks, and figuring out when to lock them
            # in a multiprocessing context.
            pool.imap(process_task, task_generator(), chunksize=1)
 
"""

if __name__ == "__main__":
    process_tasks_sequentially()
