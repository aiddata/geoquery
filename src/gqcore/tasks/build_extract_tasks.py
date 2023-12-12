from loguru import logger

from gqcore.utils.logs import get_logger
from gqcore.utils.db.extract_task_generation import generate_tasks


get_logger("generate_tasks")

logger.info("Starting generating extract tasks")

generate_tasks(overwrite=True)

logger.success("Finished generating extract tasks")
