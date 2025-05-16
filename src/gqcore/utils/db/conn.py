from contextlib import contextmanager

import psycopg
from loguru import logger
from psycopg.rows import dict_row

from gqcore import get_config


@contextmanager
def get_conn(**kwargs):
    """
    A context manager that provides a connection to the PostgreSQL database using psycopg.
    All database queries within GeoQuery should use this context manager to manage their connections.
    Keyword arguments are passed directly into the `psycopg.connect` context manager.
    """
    # FIXME: document this, or make it a separate keyword argument for this function?
    if "row_factory" not in kwargs:
        kwargs["row_factory"] = dict_row

    # fetch config
    config = get_config()

    # make database connection and yield it
    with logger.catch(exception=psycopg.Error, level="CRITICAL"):
        connect_str = f"postgres://{config['postgis_username']}:{config['postgis_password']}@{config['postgis_address']}:{config['postgis_port']}/{config['postgis_dbname']}"
        with psycopg.connect(connect_str, **kwargs) as conn:
            logger.trace("Successfully connected to database")
            yield conn


def get_static_conn(**kwargs):
    if "row_factory" not in kwargs:
        kwargs["row_factory"] = dict_row

    # fetch config
    config = get_config()

    # make database connection and yield it
    with logger.catch(exception=psycopg.Error, level="CRITICAL"):
        connect_str = f"postgres://{config['postgis_username']}:{config['postgis_password']}@{config['postgis_address']}:{config['postgis_port']}/{config['postgis_dbname']}"
        conn = psycopg.connect(connect_str, **kwargs)
        logger.trace("Successfully connected to database")
        return conn
