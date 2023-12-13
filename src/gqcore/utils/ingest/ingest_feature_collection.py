
import json
from pathlib import Path

from loguru import logger

from gqcore.utils.db import features as futils

@logger.catch(reraise=True)
def ingest_feature_collection(json_path: str = None, json_data: dict = None, update: bool = False, update_or_insert: bool = False) -> None:

    logger.info(f"Starting feature collection ingest")

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

    logger.info(f"Creating feature collection: {data['name']}")

    FC = futils.FeatureCollection(**data)
    if update_or_insert:
        try:
            logger.info(f"Trying to update feature collection before inserting")
            futils.update_feature_collection(FC)
        except Exception as e:
            logger.info(f"Failed to update feature collection, inserting instead")
            futils.insert_feature_collection(FC)
    elif update:
        logger.info(f"Updating feature collection")
        futils.update_feature_collection(FC)
    else:
        logger.info(f"Inserting feature collection")
        futils.insert_feature_collection(FC)

    logger.success(f"Finished feature collection ingest")
