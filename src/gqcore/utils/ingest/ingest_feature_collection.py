"""Module that handles ingesting feature collections into GeoQuery"""

import json
from pathlib import Path
from typing import Optional

from loguru import logger

from gqcore.utils.db import features as futils


@logger.catch(reraise=False)
def ingest_feature_collection(
    json_path: Optional[str] = None,
    json_data: Optional[dict] = None,
    skip_existing: bool = False,
    replace_features: bool = False,
    update_features: bool = False,
) -> None:
    """
    Ingest a feature collection into GeoQuery.

    Parameters:
        json_path: Path to JSON metadata for the dataset.
        json_data: JSON metadata for the dataset.
        skip_existing: Passed to [gqcore.utils.db.features.insert_feature_collection][]
        replace_features: Passed to [gqcore.utils.db.features.insert_feature_collection][]
        update_features: Passed to [gqcore.utils.db.features.insert_feature_collection][]
    """
    logger.info("Starting feature collection ingest")

    if json_path is None and json_data is None:
        logger.exception("Must provide either json_path or json_data")
    elif json_path is not None and json_data is not None:
        logger.exception("Must provide either json_path or json_data, not both")
    elif json_path is not None:
        logger.info(f"Reading JSON from {json_path}")
        path = Path(json_path)
        data = json.loads(path.read_text())
    else:
        logger.info("Reading JSON from data")
        data = json_data

    logger.info(f"Creating feature collection: {data['name']}")

    feature_collection = futils.FeatureCollection(**data)

    logger.info(
        f"Inserting feature collection (replace_features={replace_features}, update_features={update_features})"
    )

    futils.insert_feature_collection(
        feature_collection,
        skip_existing=skip_existing,
        replace_features=replace_features,
        update_features=update_features,
    )

    logger.success("Finished feature collection ingest")
