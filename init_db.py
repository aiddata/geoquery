from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
import shapely
import pandas as pd
import geopandas as gpd


def create_table_feature_geom(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feature_geom (
                fid        SERIAL PRIMARY KEY,
                geom       geometry NOT NULL
            );
        """)


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


def create_table_datasets(cur):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                did        SERIAL PRIMARY KEY,
                path       varchar(200),
                type       varchar(200),
                info       jsonb DEFAULT NULL
            );
        """)


def create_table_extract_tasks(cur):
    with conn.cursor() as cur:
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
    with conn.cursor() as cur:
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



def wipe_db():
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            cur.execute("""DROP TABLE feature_geom""")
            cur.execute("""DROP TABLE feature_meta""")
            cur.execute("""DROP TABLE datasets""")
            cur.execute("""DROP TABLE extract_tasks""")
            cur.execute("""DROP TABLE extract_data""")

def create_db():
    # connect to PostgreSQL
    # TODO: configurable connection options, e.g. host and password
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:

        create_table_feature_geom(conn)
        create_table_feature_meta(conn)
        create_table_datasets(conn)
        create_table_extract_tasks(conn)
        create_table_extract_data(conn)

if __name__ == "__main__":
    wipe_db()
    create_db()
