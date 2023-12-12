from pathlib import Path

from loguru import logger

from gqcore import get_config

log_dir = Path(get_config()["logging"]["log_dir"])


def add_handler(file_name: str) -> None:
    logger.add((log_dir / file_name).with_suffix(".log"))
