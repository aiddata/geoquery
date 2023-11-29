
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Json, ValidationInfo, field_validator

from utils.db.conn import get_conn


valid_status_dict = {
    -1: "error",
    0: "not started",
    1: "complete",
    2: "started",
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

def _get_valid_coverage_records():
    with get_conn() as conn:
        with conn.cursor() as cur:
            get_valid_coverage_records = "SELECT * FROM coverage WHERE status = 1"
            cur.execute(get_valid_coverage_records)
            valid_coverage = cur.fetchall()
    return valid_coverage

def _get_dataset_info(dataset_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            resource_query = "SELECT * from dataset_resources WHERE dataset_id = %s"
            cur.execute(resource_query, (dataset_id,))
            dataset_info = cur.fetchall()
            return dataset_info

def _get_processing_options(dataset_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            resource_query = "SELECT * from processing_options WHERE dataset_id = %s"
            cur.execute(resource_query, (dataset_id,))
            po_info = cur.fetchall()
            return po_info

def _add_extract_task(task: ExtractTask, overwrite: bool = False):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if overwrite:
                conflict_str = "DO UPDATE SET status = excluded.status, priority = excluded.priority, submit_time = excluded.submit_time, kwargs = excluded.kwargs"
            else:
                conflict_str = "DO NOTHING"

            insert = """
                INSERT INTO extract_tasks (resource_id, fm_id, po_id, status, priority, submit_time, kwargs)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (resource_id, fm_id, po_id)
                """
            insert += conflict_str
            cur.execute(insert, (
                task.resource_id,
                task.fm_id,
                task.po_id,
                task.status,
                task.priority,
                task.submit_time,
                task.kwargs
            ))

def generate_tasks(overwrite: bool = False):
    valid_coverage = _get_valid_coverage_records()
    if len(valid_coverage) == 0:
        Warning("No valid coverage records found in database")
        return

    # generate potential extract tasks associated with coverage,
    # then check if they exist, and create/add if they do not
    for item in valid_coverage:

        geom_id = item["geom_id"]
        dataset_id = item["dataset_id"]
        dataset_info = _get_dataset_info(dataset_id)
        po_info = _get_processing_options(dataset_id)

        for resource in dataset_info:
            resource_id = resource["id"]
            for po in po_info:
                task = ExtractTask(
                    resource_id=resource_id,
                    fm_id=geom_id,
                    po_id=po["id"],
                    status=0,
                    priority=0
                )
                _add_extract_task(task, overwrite=overwrite)



if __name__ == "__main__":
    generate_tasks(overwrite=True)
