
import itertools
import time
import concurrent.futures

import psycopg
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
    print(potential_coverage)
    print(len(potential_coverage))


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

def process(dataset_id):

    logger.info(f"Testing coverage for feature dataset {dataset_id} across all features", extra={"dataset_id": dataset_id})

    # spatial_query = """
    # SELECT
    #     datasets.name AS dname,
    #     datasets.id AS did,
    #     features.id AS fid
    # FROM datasets
    # JOIN features
    # ON ST_Contains(datasets.spatial_extent, features.shape)
    # WHERE datasets.id = %s;
    # """

    # # set all matches to 1
    # matches = cur.execute(spatial_query, (dataset_id, )).fetchall()

    # logger.info(f"Updating matched coverage for feature dataset {dataset_id}", extra={"dataset_id": dataset_id})

    # if len(matches) > 0:
    #     matched_fid_list = [x["fid"] for x in matches]
    #     match_update_query = """
    #     UPDATE coverage
    #     SET status = 1
    #     WHERE dataset_id = %s AND geom_id = ANY(%s);
    #     """
    #     print(match_update_query, (dataset_id, matched_fid_list))
    #     cur.execute(match_update_query, (dataset_id, matched_fid_list))

    logger.info(f"Updating matched coverage for feature dataset {dataset_id}", extra={"dataset_id": dataset_id})

    spatial_query = """
    UPDATE coverage
    SET status = 1
    WHERE dataset_id = %s AND geom_id = ANY(
        SELECT
            features.id AS geom_id
        FROM datasets
        JOIN features
        ON ST_Contains(datasets.spatial_extent, features.shape)
        WHERE datasets.id = %s
    );
    """
    cur.execute(spatial_query, (dataset_id, dataset_id))


    logger.info(f"Updatimg unmatched coverage for feature dataset {dataset_id}", extra={"dataset_id": dataset_id})

    # set non matches to 0
    update_query = """
    UPDATE coverage
    SET status = 0
    WHERE dataset_id = %s AND status = -1;
    """
    cur.execute(update_query, (dataset_id, ))

    conn.commit()



@logger.catch(reraise=False)
def test_coverage():

    logger.info("Testing coverage for untested records")

    coverage_items = get_coverage_records(status=-1)

    if len(coverage_items) == 0:
        logger.success("No coverage records to test")
        return

    # task_list = [(x["geom_id"], x["dataset_id"]) for x in coverage_items]
    task_list = list(set([x["dataset_id"] for x in coverage_items]))

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
