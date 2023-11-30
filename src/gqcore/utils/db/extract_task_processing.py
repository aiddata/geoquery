from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import shapely
from psycopg import Connection, Cursor
from psycopg.rows import class_row
from pydantic import BaseModel, ConfigDict, field_validator
from shapely import Geometry
from typing_extensions import Self

from .conn import get_conn


class ExtractTaskToRun(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int
    dataset_id: int
    dataset_path: Union[str, Path]
    mapped_dataset: bool
    resource_path: Path
    po_func: str
    po_short_name: str
    feature: Union[str, Geometry]

    @field_validator("dataset_path")
    @classmethod
    def convert_dataset_path(cls, p: Union[str, Path]) -> Path:
        if isinstance(p, str):
            return Path(p)
        else:
            return p

    @field_validator("resource_path")
    @classmethod
    def convert_resource_path(cls, p: Union[str, Path]) -> Path:
        if isinstance(p, str):
            return Path(p)
        else:
            return p

    @field_validator("feature")
    @classmethod
    def convert_feature(cls, g: Union[str, Geometry]) -> Geometry:
        if isinstance(g, str):
            return shapely.wkb.loads(g, hex=True)
        else:
            return g


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


def get_mappings(dataset_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            mappings = cur.execute(
                """SELECT * FROM mappings WHERE dataset_id = %s""", (dataset_id,)
            ).fetchall()
    return mappings


class LockTask:
    conn: Connection
    data: Optional[ExtractTaskToRun]
    results: List[ExtractData] = []

    def __enter__(self) -> Self:
        # open connection to database
        self.conn_context = get_conn()
        self.conn = self.conn_context.__enter__()

        with self.conn.cursor(row_factory=class_row(ExtractTaskToRun)) as cur:
            # select an unlocked task from extract_tasks, locking it
            # TODO: only select tasks that have fewer than X number of previous errors?
            #       ...this would require better error tracking, see comment in self.__exit__() below

            select_task_query = """
                UPDATE extract_tasks
                SET status = 2,
                    update_time = CURRENT_TIMESTAMP
                FROM (
                    SELECT
                        task_id,
                        datasets.id AS dataset_id,
                        datasets.path AS dataset_path,
                        datasets.mapped AS mapped_dataset,
                        dataset_resources.path AS resource_path,
                        processing_options.function AS po_func,
                        processing_options.short_name AS po_short_name,
                        features.shape AS feature
                    FROM (
                        SELECT
                            id AS task_id,
                            fm_id,
                            resource_id,
                            po_id AS processing_option_id
                        FROM extract_tasks
                        WHERE status = 0
                        ORDER BY priority DESC, submit_time ASC
                        LIMIT  1
                        FOR UPDATE SKIP LOCKED
                    )
                    LEFT OUTER JOIN feat_map
                        ON fm_id = feat_map.id
                    LEFT OUTER JOIN features
                        ON geom_id = features.id
                    LEFT OUTER JOIN dataset_resources
                        ON resource_id = dataset_resources.id
                    LEFT OUTER JOIN datasets
                        ON dataset_resources.dataset_id = datasets.id
                    LEFT OUTER JOIN processing_options
                        ON processing_option_id = processing_options.id
                )
                WHERE extract_tasks.id = task_id
                RETURNING *;
            """
            task = cur.execute(select_task_query)
            task_result = task.fetchone()

            if task_result is None:
                # there were no unlocked tasks!
                self.data = None
            else:
                self.data = task_result

            return self

    def found_task(self) -> bool:
        return self.data is not None

    def keep_alive(self) -> None:
        with self.conn.cursor() as cur:
            keep_alive_query = """
                UPDATE extract_tasks
                SET update_time = CURRENT_TIMESTAMP
                WHERE id = %s
            """
            cur.execute(keep_alive_query, (self.data.id,))

    def submit_result(self, data: ExtractData) -> None:
        # TODO: either assert that data.id == self.data.id,
        #       or build ExtractData here from parameters to enforce this
        self.results.append(data)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        # TODO: log error somewhere, if there was one? check if a result was submitted?
        #       we might want to create an extract tasks error table

        if self.data is not None:
            with self.conn.cursor() as cur:
                # if no error was thrown, and we got results, let's insert!
                if exc_type is None and len(self.results) > 0:
                    for result in self.results:
                        _insert_extract_data(cur, result)

                    mark_as_complete_query = """
                        UPDATE extract_tasks
                        SET status = 1
                        WHERE id = %s
                    """
                    cur.execute(mark_as_complete_query, (self.data.id,))
                else:
                    mark_as_error_query = """
                        UPDATE extract_tasks
                        SET status = -1
                        WHERE id = %s
                    """
                    cur.execute(mark_as_error_query, (self.data.id,))

        # commit our changes, including all extract data
        # insertions and marking as complete
        self.conn.commit()

        # closing connection closes transaction, releasing lock
        self.conn.close()

        self.conn_context.__exit__(None, None, None)
