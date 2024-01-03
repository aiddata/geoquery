import concurrent.futures

from loguru import logger

from gqcore.utils.db.helpers import get_dataset_by_id, get_coverage_records, get_processing_options_by_dataset, _insert_extract_task, insert_extract_task
from gqcore.utils.models import ExtractTask
from gqcore.utils.db.conn import get_static_conn


def process(input):
    geom_id, dataset_id, overwrite = input

    dataset_info = get_dataset_by_id(dataset_id)
    po_info = get_processing_options_by_dataset(dataset_id)

    for resource in dataset_info:
        resource_id = resource["id"]
        for po in po_info:
            logger.info(f"Generating extract task for resource {resource_id}, feature {geom_id}, processing options {po['id']}")
            task = ExtractTask(
                resource_id=resource_id,
                fm_id=geom_id,
                po_id=po["id"],
                status=0,
                priority=0,
            )
            raise Exception("test")
            _insert_extract_task(cur, task, overwrite)
            # insert_extract_task(task, overwrite)

    conn.commit()

# @logger.catch(reraise=True)
def generate_tasks(overwrite: bool = False):
    valid_coverage = get_coverage_records(status=1)
    if len(valid_coverage) == 0:
        logger.warning("No valid coverage records found in database")
        return


    # generate potential extract tasks associated with coverage,
    # then check if they exist, and create/add if they do not
    task_list = [(x["geom_id"], x["dataset_id"], overwrite) for x in valid_coverage]

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
            logger.exception(e[0])

    return len(valid_coverage)
