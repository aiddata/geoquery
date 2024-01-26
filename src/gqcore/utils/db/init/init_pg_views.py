import click
from loguru import logger
from psycopg.errors import DuplicateTable

from gqcore.utils.db.conn import get_conn
from gqcore.utils.logs import get_logger


def create_view_dataset_and_resources():
    query = """
        CREATE OR REPLACE VIEW dataset_and_resources AS
        SELECT
            d.id AS dataset_id,
            d.name AS dataset_name,
            d.description AS dataset_description,

    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(query)
            except DuplicateTable:
                # FIXME: this wouldn't ever run because the query includes
                # "CREATE OR REPLACE...", right?
                logger.info("View dataset_and_resources already exists.")
            else:
                logger.info("created view dataset_and_resources")


def create_view_coverage():
    query = """
        CREATE OR REPLACE VIEW coverage_with_dependencies AS
        SELECT
            coverage.geom_id AS geom_id,
            datasets.id AS dataset_id,
            coverage.status AS status
        FROM datasets
        JOIN coverage ON coverage.dataset_id = COALESCE(datasets.coverage_dependency, datasets.id)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            logger.info("created view coverage_with_dependencies")


def init_views():
    logger.info("creating views...")
    create_view_coverage()


if __name__ == "__main__":
    get_logger("init_database")
    init_views()
