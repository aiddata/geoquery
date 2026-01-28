from pathlib import Path
from typing import Dict, List, Optional, Union

import shapely
from loguru import logger
from psycopg import Cursor
from psycopg.rows import class_row
from pydantic import BaseModel, ConfigDict, field_validator
from shapely import Geometry
from typing_extensions import Self

from .conn import get_conn


class ExtractTaskToRun(BaseModel):
    """pydantic model for an extract task that is ready to run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int
    """ID of the extract task."""
    dataset_id: int
    """ID of the dataset associated with the extract task."""
    dataset_path: Union[str, Path]
    """Path of the dataset associated with the extract task."""
    mapped_dataset: bool
    """Whether or not the dataset associated with this extract task is a mapped dataset."""
    mappings: Optional[Dict[str, str]] = None
    """Mappings for the dataset associated with this extract task, if it is a mapped dataset."""
    resource_path: Path
    """Path to the resource associated with this extract task."""
    po_func: str
    """Function for the processing option associated with this extract task."""
    po_short_name: str
    """Short name of the processing option associated with this extract task."""
    po_kwargs: dict
    """Keyword arguments to pass into the processing option associated with this extract task"""
    feature: Union[str, Geometry]
    """Feature data associated with this extract task."""

    @field_validator("dataset_path")
    @classmethod
    def convert_dataset_path(cls, p: Union[str, Path]) -> Path:
        """Convert dataset_path to a pathlib.Path object, if it isn't one already."""
        if isinstance(p, str):
            return Path(p)
        else:
            return p

    @field_validator("resource_path")
    @classmethod
    def convert_resource_path(cls, p: Union[str, Path]) -> Path:
        """Convert resource_path to a pathlib.Path object, if it isn't one already."""
        if isinstance(p, str):
            return Path(p)
        else:
            return p

    @field_validator("feature")
    @classmethod
    def convert_feature(cls, g: Union[str, Geometry]) -> Geometry:
        """Convert feature from WKT to a shapely.Geometry object, if it was passed as a string."""
        if isinstance(g, str):
            return shapely.wkb.loads(g, hex=True)
        else:
            return g


class ExtractData(BaseModel):
    """pydantic model representing the output of an extract task."""

    id: int
    name: str
    value: Union[int, float, str]


@logger.catch(reraise=True)
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


@logger.catch(reraise=True)
def get_mappings(dataset_id: int):
    """
    Get mappings for a dataset.

    Parameters:
        dataset_id: The ID of the dataset.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            mappings = cur.execute(
                """SELECT * FROM mappings WHERE dataset_id = %s""", (dataset_id,)
            ).fetchall()
    return mappings


@logger.catch(reraise=True)
def count_available_tasks() -> int:
    """Return the number of extract tasks available in the queue."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            result = cur.execute("SELECT COUNT(*) FROM extract_tasks WHERE status = 0;")
            return result.fetchone()["count"]


class NoTaskAvailableError(RuntimeError):
    """Exception that is raised when there are no tasks available in the queue."""

    pass


class LockTask:
    """
    Class that handles locking an extract task from the queue to be ran.

    This class is intended to be used as a context manager, for example:
    ```python
    with LockTask() as locked_task:
        ... # locked_task
    ```
    When the context manager closes, any task results submitted using `LockTask.submit_result` will be inserted into the database.
    If an exception is raised from within the context manager, or no results are submitted, the task lock is released but not marked as completed.

    If there is no task available in the queue, a `NoTaskAvailableError` will be raised.
    """

    data: ExtractTaskToRun
    results: List[ExtractData]

    @logger.catch(reraise=True)
    def __init__(self) -> None:
        self.results = []

    @logger.catch(exclude=NoTaskAvailableError, reraise=True)
    def __enter__(self) -> Self:
        # open connection to database
        with get_conn() as conn:
            with conn.cursor(row_factory=class_row(ExtractTaskToRun)) as cur:
                # select an unlocked task from extract_tasks, locking it
                # TODO: only select tasks that have fewer than X number of previous errors?

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
                            processing_options.kwargs AS po_kwargs,
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
                        LEFT OUTER JOIN feature_collections
                            ON feat_map.fc_id = feature_collections.id
                    )
                    WHERE extract_tasks.id = task_id
                    AND feature_collections.active
                    AND datasets.active
                    AND processing_options.active
                    RETURNING *;
                """
                logger.debug("Searching for available tasks...")
                task = cur.execute(select_task_query)
                task_result = task.fetchone()
                if task_result is None:
                    # there were no unlocked tasks!
                    logger.info("There are no tasks available")
                    raise NoTaskAvailableError
                else:
                    logger.info("Available task found")
                    if task_result.mapped_dataset:
                        logger.debug("Retrieving mappings for task...")
                        task_result.mappings = get_mappings(task_result.dataset_id)
                    self.data = task_result

                return self

    @logger.catch(reraise=True)
    def keep_alive(self) -> None:
        """Update the locked extract task with a fresh "last updated" timestamp."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                keep_alive_query = """
                    UPDATE extract_tasks
                    SET update_time = CURRENT_TIMESTAMP
                    WHERE id = %s
                """
                cur.execute(keep_alive_query, (self.data.id,))

    @logger.catch(reraise=True)
    def submit_result(self, data: ExtractData) -> None:
        """
        Submit results of the extract task.
        This function may be called multiple times, appending new results onto a list.

        Parameters:
            data: Data to append to this extract task's results
        """
        # TODO: either assert that data.id == self.data.id,
        #       or build ExtractData here from parameters to enforce this
        self.results.append(data)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if exc_type is None and len(self.results) > 0:
                    # if no error was thrown, and we got results, let's insert!
                    logger.debug(
                        f"No error occured while processing task id {self.data.id}, inserting results..."
                    )
                    for result in self.results:
                        _insert_extract_data(cur, result)

                    mark_as_complete_query = """
                        UPDATE extract_tasks
                        SET status = 1
                        WHERE id = %s
                    """
                    cur.execute(mark_as_complete_query, (self.data.id,))
                else:
                    # there was an error in this context, let's log it
                    logger.error(exc_value)
                    mark_as_error_query = """
                        UPDATE extract_tasks
                        SET
                            status = -1,
                            error = %(error)s
                        WHERE id = %(id)s
                    """
                    cur.execute(
                        mark_as_error_query,
                        {"error": repr(exc_value), "id": self.data.id},
                    )
