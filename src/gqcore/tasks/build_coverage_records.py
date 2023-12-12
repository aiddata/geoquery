
import itertools

from loguru import logger

from gqcore.utils.models import CoverageRecord
from gqcore.utils.db.helpers import get_coverage_records, get_dataset_ids_without_coverage_dependencies, get_feature_ids, get_feat_geom_by_id, get_dataset_extent_by_id, update_coverage_status, insert_coverage_records
from gqcore.utils.logs import get_logger



def generate_coverage_records():

    logger.info("Generating coverage records")

    existing_coverage = get_coverage_records()
    existing_items = [(x["geom_id"], x["dataset_id"]) for x in existing_coverage]

    # TODO: replace query to get feature/dataset ids with single query that only
    # returns ids for which the pair does not exist in coverage table

    feature_ids = get_feature_ids()
    if len(feature_ids) == 0:
        logger.info("No features found in database")
        return

    dataset_ids = get_dataset_ids_without_coverage_dependencies()
    if len(dataset_ids) == 0:
        logger.info("No datasets found in database")
        return

    potential_coverage = list(itertools.product(feature_ids, dataset_ids))

    new_coverage = [
        CoverageRecord(**{"geom_id":x[0]["id"], "dataset_id":x[1]["id"]}) for x in potential_coverage
        if (x[0]["id"], x[1]["id"]) not in existing_items
    ]

    insert_coverage_records(new_coverage)

    logger.success("Coverage records generated")


def test_coverage():

    logger.info("Testing coverage for untested records")

    coverage_items = get_coverage_records(status=-1)

    for c in coverage_items:
        feature_id = c["geom_id"]
        dataset_id = c["dataset_id"]

        logger.info(f"Testing coverage for feature {feature_id} and dataset {dataset_id}", extra={"feature_id": feature_id, "dataset_id": dataset_id})

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

    logger.success("Coverage testing complete")


if __name__ == "__main__":
    get_logger("build_coverage_records")
    generate_coverage_records()
    test_coverage()
