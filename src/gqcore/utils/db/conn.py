from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from gqcore import get_config

@contextmanager
def get_conn(**kwargs):
    # TODO: configurable connection options, e.g. host and password
    if "row_factory" not in kwargs:
        kwargs["row_factory"] = dict_row
    config = get_config()
    with psycopg.connect(
        f'{config["database"]["type"]}://{config["database"]["user"]}:{config["database"]["password"]}@{config["database"]["address"]}:{config["database"]["port"]}', **kwargs
    ) as conn:
        yield conn
