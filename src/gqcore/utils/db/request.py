import itertools
from datetime import datetime
from typing import List, Tuple

from psycopg import Cursor
from pydantic import BaseModel, Json, field_validator

from conn import get_conn


class Request(BaseModel):
    feature_ids: List[int]
    resource_ids: List[int]
    processing_option_ids: List[int]
    date: datetime
    source: str
    contact: str
    custom_name: str
    info: str
    priority: int = 1
    data: Json

    @field_validator("priority")
    @classmethod
    def function_must_exist(cls, p: int) -> int:
        if p < 1:
            raise ValueError("request priority must be at least 1")
        return p


def insert_request(request: Request):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # build request query and insert it

            insert_request_query = """
                INSERT INTO requests (
                    date,
                    source,
                    contact,
                    custom_name,
                    info,
                    priority
                ) VALUES (
                    %(date)s,
                    %(source)s,
                    %(contact)s,
                    %(custom_name)s,
                    %(info)s,
                    %(priority)s
                ) RETURNING id;
            """

            cur.execute(insert_request_query, request)

            # get request id that was just inserted

            request_id = cur.fetchone()[0]

            insert_extract_task_query = """
                INSERT INTO extract_tasks (
                    resource_id,
                    fm_id,
                    processing_option_id,
                    priority,
                    data
                ) VALUES (
                    %(resource_id)s,
                    %(feature_id)s,
                    %(processing_option_id)s,
                    %(priority)s,
                    %(data)s
                )
                ON CONFLICT (resource_id, fm_id, processing_option_id)
                DO UPDATE SET priority = priority + %(priority)s
                RETURNING id;
            """

            per_task_ids: List[Tuple[int, int, int]] = itertools.product(
                [
                    request.resource_ids,
                    request.feature_ids,
                    request.processing_option_ids,
                ]
            )

            params_list = [
                {
                    "resource_id": ids[0],
                    "feature_id": ids[1],
                    "processing_options_id": ids[2],
                    "priority": request.priority,
                    "data": request.data,
                }
                for ids in per_task_ids
            ]

            cur.executemany(insert_extract_task_query, params_list)

            extract_task_ids: List[Tuple[int]] = cur.fetchall()

            insert_request_map_query = """
                INSERT INTO request_map (
                    req_id,
                    task_id
                ) VALUES (
                    %s,
                    %s
                );
            """

            cur.executemany(
                insert_request_map_query, [(request_id, i[0]) for i in extract_task_ids]
            )
