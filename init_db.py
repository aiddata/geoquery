import click
import psycopg
from psycopg.errors import DuplicateTable

from conn import get_conn


def init_db(overwrite: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if overwrite:
                cur.execute("DROP TABLE feat_map;")
                cur.execute("DROP TABLE features;")
                cur.execute("DROP TABLE datasets;")

            # create features table
            cur.execute(
                """
                CREATE TABLE features (
                    id      SERIAL PRIMARY KEY,
                    shape   geometry NOT NULL
                 );
            """
            )

            # create spatial index on features table
            cur.execute(
                """
                CREATE INDEX features_geom_idx ON features
                USING GIST (shape);
            """
            )

            # create datasets table
            cur.execute(
                """
                CREATE TABLE datasets (
                    id     SERIAL PRIMARY KEY,
                    name   varchar(200) UNIQUE NOT NULL
                 );
            """
            )

            # create feat_map table
            cur.execute(
                """
                CREATE TABLE feat_map (
                    dataset_id  int NOT NULL REFERENCES datasets(id),
                    geom_id     int NOT NULL REFERENCES features(id),
                    name        varchar(200),
                    grouping    varchar(100),
                    level       smallint,
                    attr        jsonb
                 );
            """
            )


@click.command()
@click.option("--overwrite/--no-overwrite", default=False)
def main(overwrite: bool) -> None:
    try:
        init_db(overwrite)
    except DuplicateTable:
        raise DuplicateTable(
            "Table(s) already exist, did you mean to use the --overwrite option?"
        )


if __name__ == "__main__":
    main()
