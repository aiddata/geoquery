from pathlib import Path

from loguru import logger

from gqcore import get_config

log_dir = Path(get_config()["logging"]["log_dir"])


def get_logger(file_name: str) -> None:
    logger.add(
        (log_dir / file_name).with_suffix(".log"),
        format="{time:YYYY-MM-DD at HH:mm:ss} | {level} | {name}:{file}:{function}:{line} | {message} | {extra}",
        rotation="1 week",
        level="DEBUG",
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )
