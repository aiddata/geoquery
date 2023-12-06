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



