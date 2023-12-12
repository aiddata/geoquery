from contextlib import contextmanager

import psycopg
from loguru import logger
from psycopg.rows import dict_row

from gqcore import get_config


@contextmanager
def get_conn(**kwargs):
    # TODO: configurable connection options, e.g. host and password
    if "row_factory" not in kwargs:
        kwargs["row_factory"] = dict_row
    config = get_config()
    with logger.catch(exception=psycopg.Error, level="CRITICAL"):
        with psycopg.connect(
            f'{config["database"]["type"]}://{config["database"]["user"]}:{config["database"]["password"]}@{config["database"]["address"]}:{config["database"]["port"]}',
            **kwargs,
        ) as conn:
            logger.trace("Successfully connected to database")
            yield conn
