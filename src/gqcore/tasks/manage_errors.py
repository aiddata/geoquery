"""
Module for handling edge-cases and errors.
"""
from datetime import datetime, timedelta

from loguru import logger

from gqcore.utils.db.extract_task_watch import free_dangling_tasks
from gqcore.utils.logs import get_logger


def manage_dangling_tasks(minutes: int = 1) -> None:
    """
    Free dangling extract tasks.

    This is a wrapper for `gqcore.utils.extract_task_watch.free_dangling_tasks` that includes detailed logging.

    Parameters:
      minutes: Locked tasks that have not been updated for this number of minutes will be freed.
    """
    get_logger("errors")

    delay = timedelta(minutes=1)

    logger.info(f"Clearing dangling tasks older than: {delay}")

    number_of_cleared_tasks = free_dangling_tasks(delay)

    logger.success(f"Cleared {number_of_cleared_tasks} dangling tasks.")


if __name__ == "__main__":
    manage_dangling_tasks()
