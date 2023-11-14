
import click
import psycopg
from psycopg.errors import DuplicateTable

from conn import get_conn


def create_table_feature_meta(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feature_meta (
                fid        SERIAL PRIMARY KEY,
                collection varchar(100) DEFAULT NULL,
                dataset    varchar(100) DEFAULT NULL,
                parent     varchar(100) DEFAULT NULL,
                level      integer DEFAULT NULL,
                attributes jsonb DEFAULT NULL
            );
        """)


def create_table_extract_tasks(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS extract_tasks (
            task_id         SERIAL PRIMARY KEY,
            fid             varchar(100),
            did             varchar(100),
            op              varchar(100),
            method          varchar(100),
            params          jsonb DEFAULT NULL,
            status          integer DEFAULT 0,
            priority        integer DEFAULT 0,
            submit_time     timestamp DEFAULT CURRENT_TIMESTAMP,
            start_time      timestamp DEFAULT NULL,
            update_time     timestamp DEFAULT NULL,
            complete_time   timestamp DEFAULT NULL,
            attempts        integer DEFAULT 0,
            error           varchar(100) DEFAULT NULL
        );
    """)


def create_table_extract_data(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS extract_data (
            fid        varchar(100),
            did        varchar(100),
            op         varchar(100),
            method     varchar(100),
            value      float,
            version    varchar(10)
        );
    """)



def init_db(overwrite: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if overwrite:
                cur.execute("DROP TABLE feature_collection;")
                cur.execute("DROP TABLE features;")
                cur.execute("DROP TABLE feat_map;")
                cur.execute("DROP TABLE datasets;")
                cur.execute("DROP TABLE dataset_resources;")
                cur.execute("DROP TABLE extract_tasks;")
                cur.execute("DROP TABLE extract_data;")


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

            create_table_feature_meta(cur)

            create_table_extract_tasks(cur)
            create_table_extract_data(cur)


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
