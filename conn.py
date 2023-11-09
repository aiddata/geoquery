from contextlib import contextmanager

import psycopg

@contextmanager
def get_conn(**kwargs):
    # TODO: configurable connection options, e.g. host and password
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432", **kwargs) as conn:
        yield conn
