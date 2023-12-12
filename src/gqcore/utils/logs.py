from pathlib import Path
from gqcore import get_config
from loguru import logger

log_dir = Path(get_config()["logging"]["log_dir"])

def add_handler(file_name: str) -> None:
    logger.add((log_dir / file_name).with_suffix(".log"))
