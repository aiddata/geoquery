
import itertools
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Json, ValidationInfo, field_validator
from shapely import wkb

from utils.db.conn import get_conn
from utils.helpers import get_coverage_records, get_dataset_ids, get_feature_ids, get_feat_geom_by_id, get_dataset_extent_by_id, update_coverage_status, insert_coverage_records

from utils.db.models import CoverageRecord


def generate_coverage_records():

    existing_coverage = get_coverage_records()
    existing_items = [(x["geom_id"], x["dataset_id"]) for x in existing_coverage]

    feature_ids = get_feature_ids()
    if len(feature_ids) == 0:
        raise ValueError("No features found in database")
    dataset_ids = get_dataset_ids()
    if len(dataset_ids) == 0:
        raise ValueError("No datasets found in database")

    potential_coverage = list(itertools.product(feature_ids, dataset_ids))

    new_coverage = [
        CoverageRecord(**{"geom_id":x[0]["id"], "dataset_id":x[1]["id"]}) for x in potential_coverage
        if (x[0]["id"], x[1]["id"]) not in existing_items
    ]

    insert_coverage_records(new_coverage)


def test_coverage():

    coverage_items = get_coverage_records(status=-1)

    for c in coverage_items:
        feature_id = c["geom_id"]
        dataset_id = c["dataset_id"]

        feature_geom = get_feat_geom_by_id(feature_id)

        dataset_spatial_extent = get_dataset_extent_by_id(dataset_id)

        # compare feature geom to dataset spatial_extent
        # if feature geom is within dataset spatial_extent, set coverage to 1
        # else set coverage to 0

        if feature_geom.within(dataset_spatial_extent):
            new_status = 1
        else:
            new_status = 0

        update_coverage_status(feature_id, dataset_id, new_status)


if __name__ == "__main__":
    generate_coverage_records()
    test_coverage()
