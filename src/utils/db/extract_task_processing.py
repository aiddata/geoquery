from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from psycopg import Connection, Cursor
from psycopg.rows import class_row
from pydantic import BaseModel, Json, ValidationInfo, field_validator
from typing_extensions import Self

from utils.db.conn import get_conn
from extract_task_generation import ExtractTask


class ExtractTaskFromDB(ExtractTask):
    id: int


class ExtractData(BaseModel):
    id: int
    name: str
    value: Union[int, float, str]



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
