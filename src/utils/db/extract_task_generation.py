from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Json, ValidationInfo, field_validator
from utils.helpers import (_get_coverage_records, _get_dataset_by_id,
                           _get_processing_options_by_dataset,
                           _insert_extract_task)

valid_status_dict = {
    -1: "error",
    0: "not started",
    1: "complete",
    # 2: "started",
}


class ExtractTask(BaseModel):
    resource_id: int
    fm_id: int
    po_id: int
    status: Optional[int]
    priority: Optional[int]
    submit_time: Optional[datetime] = datetime.now()
    # start_time: Optional[datetime]
    # update_time: Optional[datetime]
    # complete_time: Optional[datetime]
    # attempts: Optional[int]
    # error: Optional[str]
    kwargs: Optional[dict] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, s: int) -> int:
        if s not in valid_status_dict:
            raise ValueError(
                "status must be one of the following: {}".format(valid_status_dict)
            )
        return s


def generate_tasks(overwrite: bool = False):
    valid_coverage = _get_coverage_records(status=1)
    if len(valid_coverage) == 0:
        Warning("No valid coverage records found in database")
        return

    # generate potential extract tasks associated with coverage,
    # then check if they exist, and create/add if they do not
    for item in valid_coverage:
        geom_id = item["geom_id"]
        dataset_id = item["dataset_id"]
        dataset_info = _get_dataset_by_id(dataset_id)
        po_info = _get_processing_options_by_dataset(dataset_id)

        for resource in dataset_info:
            resource_id = resource["id"]
            for po in po_info:
                task = ExtractTask(
                    resource_id=resource_id,
                    fm_id=geom_id,
                    po_id=po["id"],
                    status=0,
                    priority=0,
                )
                _insert_extract_task(task, overwrite=overwrite)
