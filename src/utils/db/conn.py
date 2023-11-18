from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


@contextmanager
def get_conn(**kwargs):
    # TODO: configurable connection options, e.g. host and password
    if "row_factory" not in kwargs:
        kwargs["row_factory"] = dict_row
    with psycopg.connect(
        "postgresql://postgres:mysecretpassword@localhost:5432", **kwargs
    ) as conn:
        yield conn
