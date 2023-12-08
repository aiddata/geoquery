import click
from psycopg.errors import DuplicateTable

from gqcore.utils.db.conn import get_conn


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
                click.echo("View dataset_and_resources already exists.")


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


if __name__ == "__main__":
    create_view_coverage()
