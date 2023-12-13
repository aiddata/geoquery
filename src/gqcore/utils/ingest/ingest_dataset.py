import json
from pathlib import Path

from loguru import logger

from gqcore.utils.db import dataset as dutils


@logger.catch(reraise=True)
def ingest_dataset(
    json_path: str = None,
    json_data: dict = None,
    update: bool = False,
    update_or_insert: bool = False,
) -> None:

    logger.info(f"Starting dataset ingest")
    if json_path is None and json_data is None:
        logger.exception("Must provide either json_path or json_data")
    elif json_path is not None and json_data is not None:
        logger.exception("Must provide either json_path or json_data, not both")
    elif json_path is not None:
        logger.info(f"Reading json from {json_path}")
        path = Path(json_path)
        data = json.loads(path.read_text())
    else:
        logger.info(f"Reading json from data")
        data = json_data

    DS = dutils.Dataset(**data)
    if update_or_insert:
        try:
            logger.info(f"Trying to update dataset before inserting")
            dutils.update_dataset(DS)
        except Exception as e:
            logger.info(f"Failed to update dataset, inserting instead")
            dutils.insert_dataset(DS)
    elif update:
        logger.info(f"Updating dataset")
        dutils.update_dataset(DS)
    else:
        logger.info(f"Inserting dataset")
        dutils.insert_dataset(DS)

    logger.success(f"Finished dataset ingest")
