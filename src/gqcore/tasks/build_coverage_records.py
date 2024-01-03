
import itertools
import time
import concurrent.futures

from loguru import logger

from gqcore.utils.logs import get_logger
from gqcore.utils.models import CoverageRecord
from gqcore.utils.db.helpers import get_coverage_records, get_dataset_ids_without_coverage_dependencies, get_feature_ids, get_feat_geom_by_id, get_dataset_extent_by_id, update_coverage_status, _update_coverage_status, insert_coverage_records, find_missing_coverage_id_pairs
from gqcore.utils.db.conn import get_conn, get_static_conn

@logger.catch(reraise=False)
def generate_coverage_records():

    logger.info("Generating coverage records")

    feature_ids = get_feature_ids()
    if len(feature_ids) == 0:
        logger.info("No features found in database")
        return

    dataset_ids = get_dataset_ids_without_coverage_dependencies()
    if len(dataset_ids) == 0:
        logger.info("No datasets without dependencies found in database")
        return

    t_start = time.perf_counter()

    potential_coverage = find_missing_coverage_id_pairs()

    if len(potential_coverage) == 0:
        logger.success("No coverage records to generate")
        return

    new_coverage = [
        CoverageRecord(**{"geom_id":x["geom_id"], "dataset_id":x["dataset_id"]}) for x in potential_coverage
    ]

    insert_coverage_records(new_coverage)

    t_end = time.perf_counter()

    logger.info(f"Time to generate and insert {len(new_coverage)} coverage records: {t_end - t_start:0.4f} seconds")

    logger.success("Coverage records generated")


def process(task):

        feature_id, dataset_id = task

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

        _update_coverage_status(cur, feature_id, dataset_id, new_status)
        conn.commit()


@logger.catch(reraise=False)
def test_coverage():

    logger.info("Testing coverage for untested records")

    coverage_items = get_coverage_records(status=-1)

    if len(coverage_items) == 0:
        logger.success("No coverage records to test")
        return

    task_list = [(x["geom_id"], x["dataset_id"]) for x in coverage_items]

    # ============

    t_start = time.perf_counter()

    def processor_init():
        global conn, cur
        conn = get_static_conn()
        cur = conn.cursor()

    with concurrent.futures.ProcessPoolExecutor(initializer=processor_init, max_workers=None) as executor:

        futures = [executor.submit(process, t) for t in task_list]

        e = []
        for result in concurrent.futures.as_completed(futures):
            if result.exception() is not None:
                e.append(result.exception())

        if len(e) > 0:
            logger.error(f"{len(e)} exceptions occurred")
            unique_e = set([str(x) for x in e])
            logger.error(f"{len(unique_e)} unique exceptions occurred:")
            logger.error(f"Unique exceptions: {unique_e}")
            raise e[0]


    t_end = time.perf_counter()

    logger.info(f"Time to test and update coverage for {len(coverage_items)} records: {t_end - t_start:0.4f} seconds")
    logger.info(f"Avg time to test and update coverage: {(t_end - t_start)/len(coverage_items):0.4f} seconds")


    logger.success("Coverage testing complete")


if __name__ == "__main__":
    get_logger("build_coverage_records")
    generate_coverage_records()
    test_coverage()
