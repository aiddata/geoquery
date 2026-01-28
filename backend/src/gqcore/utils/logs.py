"""Module to handle logs across entire GeoQuery backend."""

import sys
from pathlib import Path

from loguru import logger

from gqcore import get_config


def get_logger(file_name: str) -> None:
    """
    Set up a loguru logging handler.

    Parameters:
      file_name: Name of log file to use (required, but not currently used)
    """
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD at HH:mm:ss} | {level} | {name}:{file}:{function}:{line} | {message} | {extra}",
        level="DEBUG",
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )
    # logger.add(
    #     (log_dir / file_name).with_suffix(".log"),
    #     format="{time:YYYY-MM-DD at HH:mm:ss} | {level} | {name}:{file}:{function}:{line} | {message} | {extra}",
    #     rotation="1 week",
    #     level="DEBUG",
    #     backtrace=True,
    #     diagnose=True,
    #     enqueue=True,
    # )
