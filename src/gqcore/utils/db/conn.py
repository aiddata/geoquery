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
    db_config = config["database"]

    # try fetching secrets from k8s
    secrets_dir = Path("/secrets/db")
    if secrets_dir.is_dir():
        logger.info("Secrets directory found, loading secrets...")
        for s in secrets_dir.iterdir():
            try:
                with open(s) as src:
                    db_config[s.name] = src.read()
                    logger.debug(f"Loaded secret {s.name}")
            except Exception as e:
                logger.warning(f"Error loading secret {s.name}: {e}")
    else:
        logger.debug(
            "No secrets directory found, continuing with values from config.toml"
        )

    # make database connection and yield it
    with logger.catch(exception=psycopg.Error, level="CRITICAL"):
        with psycopg.connect(
            f'{db_config["type"]}://{db_config["user"]}:{db_config["password"]}@{db_config["address"]}:{db_config["port"]}',
            **kwargs,
        ) as conn:
            logger.trace("Successfully connected to database")
            yield conn
