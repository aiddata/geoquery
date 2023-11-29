from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from psycopg import Connection, Cursor
from psycopg.rows import class_row
from pydantic import BaseModel, Json, ValidationInfo, field_validator
from typing_extensions import Self

from utils.db.conn import get_conn

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


class ExtractTaskFromDB(ExtractTask):
    id: int


class ExtractData(BaseModel):
    id: int
    name: str
    value: Union[int, float, str]


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
            cur.execute(
                insert,
                (
                    task.resource_id,
                    task.fm_id,
                    task.po_id,
                    task.status,
                    task.priority,
                    task.submit_time,
                    task.kwargs,
                ),
            )


def _insert_extract_data(cur: Cursor, data: ExtractData) -> None:
    add_result_query = """
        INSERT INTO extract_data (
            id,
            name,
            data_column,
            float_value,
            int_value,
            str_value
        ) VALUES (
            %(id)s,
            %(name)s,
            %(data_column)s,
            %(float_value)s,
            %(int_value)s,
            %(str_value)s
        );
    """

    params = dict(data)

    params["float_value"], params["int_value"], params["str_value"] = None, None, None

    if isinstance(params["value"], int):
        params["data_column"] = "int"
        params["int_value"] = params["value"]
    elif isinstance(params["value"], float):
        params["data_column"] = "float"
        params["float_value"] = params["value"]
    elif isinstance(params["value"], str):
        params["data_column"] = "str"
        params["str_value"] = params["value"]

    cur.execute(add_result_query, params)


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
                    priority=0,
                )
                _add_extract_task(task, overwrite=overwrite)


class LockTask:
    conn: Connection
    cur: Cursor
    data: Optional[ExtractTaskFromDB]

    def __enter__(self) -> Self:
        # open connection to database
        self.conn_context = get_conn()
        self.conn = self.conn_context.__enter__()
        self.cur = self.conn.cursor(row_factory=class_row(ExtractTaskFromDB))

        # select an unlocked task from extract_tasks, locking it
        # TODO: only select tasks that have fewer than X number of previous errors?
        #       ...this would require better error tracking, see comment in self.__exit__() below
        select_task_query = """
            SELECT *
            FROM extract_tasks
            WHERE status = 0
            ORDER BY priority DESC, submit_time ASC
            LIMIT  1
            FOR UPDATE SKIP LOCKED
        """
        task = self.cur.execute(select_task_query)
        task_result = task.fetchone()

        if task_result is None:
            # there were no unlocked tasks!
            self.data = None
        else:
            self.data = task_result

        # TODO: ensure that a dropped connection (plug gets pulled) means that task gets unlocked
        #       ...this might require some kind of idle timeout procedure? Need to investigate

        return self

    def submit_result(self, data: ExtractData) -> None:
        # TODO: either assert that data.id == self.data.id,
        #       or build ExtractData here from parameters to enforce this
        _insert_extract_data(self.cur, data)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        # TODO: log error somewhere, if there was one? check if a result was submitted?
        #       we might want to create an extract tasks error table

        # if no error was thrown, and we were working on a real task, task is complete!
        if exc_type is None and self.data is not None:
            mark_as_complete_query = """
                UPDATE extract_tasks
                SET status = 1
                WHERE id = %s
            """
            self.cur.execute(mark_as_complete_query, (self.data.id,))

        # commit our changes, including all extract data insertions and marking as complete
        self.conn.commit()

        # closing connection closes transaction, releasing lock
        self.conn.close()

        self.conn_context.__exit__(None, None, None)


if __name__ == "__main__":
    generate_tasks(overwrite=True)
