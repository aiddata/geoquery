import builtins
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import utils.processors
from utils.db.extract_task_processing import (ExtractData, LockTask,
                                              get_mappings)


def run_op(feat, data, func, **kwargs):
    results = func(feat, data, **kwargs)
    return results


def get_func(op):
    """Get appropriate function for operation."""
    if hasattr(utils.processors, op):
        func = getattr(utils.processors, op)
    else:
        raise ValueError(f"Operation {op} not supported.")
    return func


def run_extract():
    """
    Main function to run an extraction of a dataset to a feature
    Contains the following steps:
    - get an extract task
    - prepare task components
    - send task to function to run necessary operation
    - receive and prepare results
    - export results
    """

    # get a task, locked just for us!
    with LockTask() as task:
        if task.found_task():
            path = Path(task.data.dataset_path) / task.data.resource_path
            func = get_func(task.data.po_func)
            op_kwargs = {"stat": task.data.po_short_name}

            # TODO: I'd prefer if get_mappings was done internally by LockTask,
            #       and exposed within ExtractTaskToRun
            if task.data.mapped_dataset:
                map = get_mappings(task.data.dataset_id)
                op_kwargs["category_map"] = {i["map_val"]: i["map_name"] for i in map}

            result = run_op(task.data.feature, path, func, **op_kwargs)

            for method, val in result:
                # FIXME: the following (commented) line doesn't need to exist.
                #        At the end of the day, it should be Postgres that
                #        checks result type on insert and raise an error if
                #        there was a bad insertion. At the very least, our
                #        context manager should check for us.
                # val = getattr(builtins, po["result_type"])(val)

                result = ExtractData(
                    id=task.data.id,
                    name=method,
                    value=val,
                )

                # submit our ExtractData object for insertion
                task.submit_result(result)
            else:
                Warning("No available tasks to complete!")


if __name__ == "__main__":
    run_extract()
