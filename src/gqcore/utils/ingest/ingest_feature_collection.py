
import json
from pathlib import Path

from loguru import logger

from gqcore.utils.db import features as futils

@logger.catch(reraise=False)
def ingest_feature_collection(json_path: str = None, json_data: dict = None, skip_existing:bool=False, update_meta:bool=False, replace_features:bool=False, update_features:bool=False) -> None:

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


    logger.info(f"Inserting feature collection (update_meta={update_meta}, replace_features={replace_features}, update_features={update_features}))")
    futils.insert_feature_collection(FC, skip_existing=skip_existing, update_meta=update_meta, replace_features=replace_features, update_features=update_features)

    logger.success(f"Finished feature collection ingest")
