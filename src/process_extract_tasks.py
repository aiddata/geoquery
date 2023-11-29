import builtins
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg
import rasterstats as rs
import shapely
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Json, ValidationInfo, field_validator

import utils.processors
from utils.db.conn import get_conn
from utils.db.extract_tasks import ExtractData, LockTask


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
        if task.data is not None:
            feat = get_feat(task.data.fm_id)
            resource = get_dataset_resource(task.data.resource_id)
            dataset = get_dataset(resource["dataset_id"])
            path = dataset["path"] + "/" + resource["path"]
            po = get_processing_option(task.data.po_id)

            func = get_func(po["function"])

            method = po["short_name"]

            op_kwargs = {"stat": method}
            if dataset["mapped"] == True:
                map = get_mappings(dataset["id"])
                op_kwargs["category_map"] = {i["map_val"]: i["map_name"] for i in map}

            result = run_op(feat, path, func, **op_kwargs)

            for method, val in result:
                # FIXME: this likely doesn't need to exist. At the end of the day,
                #        it should be Postgres that checks result type on insert
                #        and raise an error if there was a bad insertion.
                #        At the very least, our context manager should check for us.
                val = getattr(builtins, po["result_type"])(val)

                result = ExtractData(
                    id=task.data.id,
                    name=method,
                    value=val,
                )

                # submit our ExtractData object for insertion
                task.submit_result(result)
            else:
                Warning("No available tasks to complete!")


def update_extract_task(task_id, status, update_type):
    """Update the status of an extract task"""
    if update_type not in ["update", "complete"]:
        raise ValueError(f"Update type {update_type} not supported.")
    update_str = f"{update_type}_time"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                psycopg.sql.SQL(
                    """
                UPDATE extract_tasks
                SET    status = %s, {} = CURRENT_TIMESTAMP
                WHERE  id = %s;
                """
                ).format(psycopg.sql.Identifier(update_str)),
                (status, task_id),
            )


def get_feat(fid):
    """GET FEATURE FROM FEATURE TABLE"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            feat = cur.execute(
                """SELECT * FROM features WHERE id = %s""", (fid,)
            ).fetchone()
    geom = shapely.wkb.loads(feat["shape"], hex=True)

    return geom


def get_dataset_resource(resource_id):
    """GET DATASET RESOURCE FROM DATASET RESOURCE TABLE"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            resource = cur.execute(
                """SELECT * FROM dataset_resources WHERE id = %s""", (resource_id,)
            ).fetchone()

    return resource


def get_dataset(did):
    """GET DATA META FROM DATA TABLE AND ASSOCIATED PATH/INFO FOR ACTUAL DATASET"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            data = cur.execute(
                """SELECT * FROM datasets WHERE id = %s""", (did,)
            ).fetchone()

    return data


def get_processing_option(po_id):
    """Get processing option from processing options table."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            po = cur.execute(
                """SELECT * FROM processing_options WHERE id = %s""", (po_id,)
            ).fetchone()

    return po


def get_mappings(dataset_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            mappings = cur.execute(
                """SELECT * FROM mappings WHERE dataset_id = %s""", (dataset_id,)
            ).fetchall()
    return mappings


def run_op(feat, data, func, **kwargs):
    results = func(feat, data, **kwargs)
    return results


def export_result(result):
    """EXPORT RESULT TO EXTRACT RESULT TABLE"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            status = insert_result(cur, result)
    return status


def insert_result(cur, result):
    cur.execute(
        """
        INSERT INTO extract_data (id, name, data_column, float_value, int_value, str_value)
        VALUES (%s, %s, %s, %s, %s, %s);
        """,
        (
            result.id,
            result.name,
            result.data_column,
            result.float_value,
            result.int_value,
            result.str_value,
        ),
    )


def get_func(op):
    """Get appropriate function for operation."""
    if hasattr(utils.processors, op):
        func = getattr(utils.processors, op)
    else:
        raise ValueError(f"Operation {op} not supportedx.")
    return func
