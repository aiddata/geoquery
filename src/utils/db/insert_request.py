from datetime import datetime

from conn import get_conn
from pydantic import BaseModel, field_validator


class Request(BaseModel):
    date: datetime
    source: str
    contact: str
    custom_name: str
    info: str
    priority: int = 1

    @field_validator("priority")
    @classmethod
    def function_must_exist(cls, p: int) -> int:
        if p < 1:
            raise ValueError("request priority must be at least 1")
        return p


def insert_request(request: Request):
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = ""  # TODO

            cur.execute(query, request)

            # TODO: insert into extract_tasks, request_map
