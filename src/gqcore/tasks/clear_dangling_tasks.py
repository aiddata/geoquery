from datetime import datetime, timedelta

from loguru import logger

from gqcore.utils.logs import get_logger
from gqcore.utils.db.extract_task_watch import free_dangling_tasks


get_logger("clear_dangling_tasks")

delay = timedelta(minutes=1)

logger.info("Clearing dangling tasks older than: {delay}")

number_of_cleared_tasks = free_dangling_tasks(delay)

logger.success(f"Cleared {number_of_cleared_tasks} dangling tasks.")
