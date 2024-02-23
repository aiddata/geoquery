"""
Module for processing new and complete requests
"""
from loguru import logger

from gqcore.utils.db.request_processing import (
    process_completed_requests,
    process_new_requests,
)
from gqcore.utils.logs import get_logger


def process_requests() -> None:
    """
    Process new and completed requests.
    """

    get_logger("process_requests")

    logger.info("Processing new requests")
    process_new_requests()
    logger.info("Finished processing new requests")

    logger.info("Processing completed requests")
    process_completed_requests()
    logger.info("Finished processing completed requests")


if __name__ == "__main__":
    process_requests()
