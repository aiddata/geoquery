"""Module that handles ingesting datasets into GeoQuery"""

import json
from pathlib import Path

from loguru import logger

from gqcore.utils.db import dataset as dutils


@logger.catch(reraise=True)
def ingest_dataset(
    json_data: dict | Path,
    update: bool = False,
    update_or_insert: bool = False,
) -> None:
    """
    Ingest a dataset into GeoQuery.
    You must provide either the `json_path` or `json_data` parameter, but not both.

    Parameters:
        json_data: Path to JSON metadata, or a JSON dict, representing the dataset.
        update: Update the dataset (expecting it to already exist in the database).
        update_or_insert: Try to update the dataset, inserting it if it doesn't already exist.
    """
    if isinstance(json_data, Path):
        logger.info(f"Reading JSON from {json_data}")
        data = json.loads(json_data.read_text())
    elif isinstance(json_data, dict):
        logger.info("Reading JSON from data")
        data = json_data
    else:
        logger.exception("json must either be a dictionary or Path object")

    dataset = dutils.Dataset(**data)

    if update_or_insert:
        try:
            logger.info("Trying to update dataset before inserting")
            dutils.update_dataset(dataset)
        except Exception:
            logger.info("Failed to update dataset, inserting instead")
            dutils.insert_dataset(dataset)
    elif update:
        logger.info("Updating dataset")
        dutils.update_dataset(dataset)
    else:
        logger.info("Inserting dataset")
        dutils.insert_dataset(dataset)

    logger.success("Finished dataset ingest")
