from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Json, ValidationInfo, field_validator

from gqcore.utils.db.helpers import get_dataset_by_id, get_coverage_records, get_processing_options_by_dataset, insert_extract_task
from gqcore.utils.models import ExtractTask



def generate_tasks(overwrite: bool = False):
    valid_coverage = get_coverage_records(status=1)
    if len(valid_coverage) == 0:
        Warning("No valid coverage records found in database")
        return

    # generate potential extract tasks associated with coverage,
    # then check if they exist, and create/add if they do not
    for item in valid_coverage:
        geom_id = item["geom_id"]
        dataset_id = item["dataset_id"]
        dataset_info = get_dataset_by_id(dataset_id)
        po_info = get_processing_options_by_dataset(dataset_id)

        for resource in dataset_info:
            resource_id = resource["id"]
            for po in po_info:
                task = ExtractTask(
                    resource_id=resource_id,
                    fm_id=geom_id,
                    po_id=po["id"],
                    status=0,
                    priority=0,
                )
                insert_extract_task(task, overwrite=overwrite)
