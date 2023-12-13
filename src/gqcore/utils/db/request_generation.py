from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Json, field_validator
from loguru import logger

from gqcore.utils.db.conn import get_conn


class RequestItem(BaseModel):
    dr_id: int
    fm_id: int
    po_id: int
    priority: Optional[int] = 0


class Request(BaseModel):
    source: str
    contact: str
    custom_name: str
    info: str
    priority: int = 1
    data: List[RequestItem] # each item in list is a list containing resource_id, feat_map_id, processing_option_id

    @field_validator("priority")
    @classmethod
    def function_must_exist(cls, p: int) -> int:
        if p < 0:
            raise ValueError("request priority must be at least 1")
        return p


@logger.catch(reraise=True)
def insert_request(request: Request):

    params = request.model_dump()
    params["date"] = datetime.now()
    params["status"] = -1

    logger.info(f"Inserting new request {params['date']}")

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
                    priority,
                    status
                ) VALUES (
                    %(date)s,
                    %(source)s,
                    %(contact)s,
                    %(custom_name)s,
                    %(info)s,
                    %(priority)s,
                    %(status)s

                ) RETURNING id;
            """

            cur.execute(insert_request_query, params)

            # get request id that was just inserted

            request_id = cur.fetchone()["id"]
            logger.info(f"Inserted new request {request_id} and preparing associated tasks")

            params_list = []
            for i in request.data:
                request_data_item = i.model_dump()
                fid_query = """SELECT geom_id FROM feat_map WHERE id = %s"""
                cur.execute(fid_query, (request_data_item["fm_id"],))
                fid = cur.fetchone()["geom_id"]
                extract_task_item = {
                    "resource_id": request_data_item["dr_id"],
                    "feature_id": fid,
                    "processing_option_id": request_data_item["po_id"],
                    "priority": request.priority
                }
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

            logger.success(f"Inserted new request {request_id} and associated tasks {extract_task_ids}")
