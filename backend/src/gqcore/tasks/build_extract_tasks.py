import time

from loguru import logger

from gqcore.utils.db.extract_task_generation import generate_tasks
from gqcore.utils.logs import get_logger

if __name__ == "__main__":

    get_logger("build_extract_tasks")

    logger.info("Starting generating extract tasks")

    t_start = time.perf_counter()
    task_count = generate_tasks(overwrite=False)
    t_end = time.perf_counter()

    logger.success("Finished generating extract tasks")

    logger.info(
        f"Time to generate tasks for {task_count} records: {t_end - t_start:0.4f} seconds"
    )

    if task_count > 0:
        logger.info(
            f"Avg time to generate tasks: {(t_end - t_start)/task_count:0.4f} seconds"
        )
