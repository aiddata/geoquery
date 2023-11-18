
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Json, ValidationInfo, field_validator

from utils.db.conn import get_conn

valid_status_dict = {
    -1: "not started",
    0: "no coverage",
    1: "coverage",
}


class CoverageRecord(BaseModel):
    geom_id: int
    dataset_id: int
    status: Optional[int] = 0

    @field_validator("status")
    @classmethod
    def validate_statusn(cls, s: int) -> int:
        if s not in valid_status_dict:
            raise ValueError(
                "status must be one of the following: {}".format(valid_status_dict)
            )
        return s
