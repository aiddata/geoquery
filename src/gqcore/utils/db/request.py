import itertools
from datetime import datetime
from typing import List, Tuple

from psycopg import Cursor
from pydantic import BaseModel, Json, field_validator

from gqcore.utils.db.conn import get_conn


class Request(BaseModel):
    source: str
    contact: str
    custom_name: str
    info: str
    priority: int = 1
    data: List[List[int]] # each item in list is a list containing resource_id, feature_id, processing_option_id

    @field_validator("priority")
    @classmethod
    def function_must_exist(cls, p: int) -> int:
        if p < 0:
            raise ValueError("request priority must be at least 1")
        return p



def insert_request(request: Request):
    params = request.model_dump()
    params["date"] = datetime.now()

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

            cur.execute(insert_request_query, params)

            # get request id that was just inserted

            request_id = cur.fetchone()["id"]

            params_list = []
            for i in request.data:
                extract_task_item = dict(zip(["resource_id", "feature_id", "processing_option_id"], i))
                extract_task_item["priority"] = request.priority
                params_list.append(extract_task_item)


            insert_extract_task_query = """
                INSERT INTO extract_tasks (
                    resource_id,
                    fm_id,
                    po_id,
                    priority
                ) VALUES (
                    %(resource_id)s,
                    %(feature_id)s,
                    %(processing_option_id)s,
                    %(priority)s
                )
                ON CONFLICT (resource_id, fm_id, po_id)
                DO UPDATE SET priority = %(priority)s
                RETURNING id;
            """

            cur.executemany(insert_extract_task_query, params_list, returning=True)
            extract_task_ids = []
            while True:
                extract_task_ids.append(cur.fetchone()["id"])
                if not cur.nextset():
                    break

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
                insert_request_map_query, [(request_id, i) for i in extract_task_ids], returning=True
            )


if __name__ == "__main__":
    request = Request(**{
        "source": "script",
        "contact": "sgoodman@aiddata.wm.edu",
        "custom_name": "test",
        "info": "Nothing",
        "data": [[1, 1, 1], [1, 2, 1], [1, 3, 1], [1, 4, 1],
                 [2, 1, 1], [2, 2, 1], [2, 3, 1], [2, 4, 1]],
    })
    insert_request(request)
