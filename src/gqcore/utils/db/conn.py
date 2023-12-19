from pathlib import Path
from contextlib import contextmanager

import psycopg
from loguru import logger
from psycopg.rows import dict_row

from gqcore import get_config


@contextmanager
def get_conn(**kwargs):
    if "row_factory" not in kwargs:
        kwargs["row_factory"] = dict_row

    # fetch config
    config = get_config()

    # make database connection and yield it
    with logger.catch(exception=psycopg.Error, level="CRITICAL"):
        with psycopg.connect(
            f'postgres://{config["postgis_username"]}:{config["postgis_password"]}@{config["postgis_address"]}:{config["postgis_port"]}/{config["postgis_dbname"]}',
            **kwargs,
        ) as conn:
            logger.trace("Successfully connected to database")
            yield conn
