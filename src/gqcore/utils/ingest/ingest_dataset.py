import json
from pathlib import Path

from loguru import logger

from gqcore.utils.db import dataset as dutils


@logger.catch
def ingest_dataset(
    json_path: str = None,
    json_data: dict = None,
    update: bool = False,
    update_or_insert: bool = False,
) -> None:
    if json_path is None and json_data is None:
        raise ValueError("Must provide either json_path or json_data")
    elif json_path is not None and json_data is not None:
        raise ValueError("Must provide either json_path or json_data, not both")
    elif json_path is not None:
        path = Path(json_path)
        data = json.loads(path.read_text())
    else:
        data = json_data

    DS = dutils.Dataset(**data)
    if update_or_insert:
        try:
            dutils.update_dataset(DS)
        except Exception as e:
            dutils.insert_dataset(DS)
    elif update:
        dutils.update_dataset(DS)
    else:
        dutils.insert_dataset(DS)
