"""
Module to orchestrate database initialization.
"""
from loguru import logger

from gqcore.utils.db.init import init_pg_tables, init_pg_views
from gqcore.utils.k8s.cluster import wait_for_db
from gqcore.utils.logs import get_logger


def init_db() -> None:
    """
    Run database initialization utilities in order.

    1. Wait for database to come online
    2. Create tables
    3. Create views
    """
    get_logger("init_database")

    # wait for database to come online
    wait_for_db()

    logger.info("initializing database...")

    # create tables
    init_pg_tables.init_db(False)

    # create views
    init_pg_views.init_views()

    logger.info("finished initializing database.")


if __name__ == "__main__":
    init_db()
