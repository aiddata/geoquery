
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
    processing_options_id: int
    status: int
    priority: int
    submit_time: datetime
    start_time: datetime
    update_time: datetime
    complete_time: datetime
    attempts: int
    error: str
    kwargs: Optional[dict] = None

    @field_validator("function")
    @classmethod
    def validate_status(cls, s: int) -> int:
        if s not in valid_status_dict:
            raise ValueError(
                "status must be one of the following: {}".format(valid_status_dict)
            )
        return s
