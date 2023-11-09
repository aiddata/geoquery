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


def get_gb_data(iso3="GHA", adm="ADM1"):
    src = Path(f"/home/userx/Desktop/geoquery-update/data/geoBoundaries-{iso3}-{adm}-all/geoBoundaries-{iso3}-{adm}.geojson")
    df = gpd.read_file(src)
    return df


def insert_dummy_feature_geom(conn):
    with conn.cursor() as cur:
        data = pd.concat([get_gb_data("GHA", "ADM0"), get_gb_data("GHA", "ADM1"), get_gb_data("GHA", "ADM2")])
        # iterate through rows of df
        for ix, row in enumerate(data.to_dict(orient="records")):
            fid = insert_feature_geom(cur, row)
            fid = fid.fetchall()[0][0]
            insert_feature_meta(cur, fid, row)


# def insert_dummy_feature_geom(cur):
#     with conn.cursor() as cur:
#         adm_level = 1
#         print(f"Loading ADM{adm_level}...")
#         src = Path(f"data/geoBoundariesCGAZ_ADM{adm_level}.gpkg")
#         # load this file into a geopandas df
#         df = gpd.read_file(src)
#         # iterate through rows of df
#         # NOTE: there may be faster ways to iterate
#         for ix, row in enumerate(df.to_dict(orient="records")):
#             insert_row(cur, row)
#             if ix > 10:
#                 break

# function to insert row from geopandas df into boundaries table
def insert_feature_geom(cur, row):
    fid = cur.execute("""
        INSERT INTO feature_geom (geom)
        VALUES (ST_GeomFromText(%s))
        RETURNING fid;
        """,
        ( shapely.to_wkt(row["geometry"]), )
    )
    return fid


def insert_feature_meta(cur, fid, row):
    cur.execute("""
        INSERT INTO feature_meta (fid)
        VALUES (%s);
        """,
        ( fid, )
    )

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

def insert_dummy_datasets(conn):
    with conn.cursor() as cur:
        esa_cmap = {
            "urban" : 190,
            "bare_areas" : 200,
            "sparse_vegetation" : 140,
            "snow_ice" : 220,
            "shrubland" : 120,
            "no_data" : 0,
            "mosaic_cropland" : 30,
            "rainfed_cropland" : 10,
            "wetland" : 180,
            "forest" : 50,
            "grassland" : 110,
            "water_bodies" : 210,
            "irrigated_cropland" : 20
        }
        data = [
            ("/home/userx/Desktop/geoquery-update/data/avhrr_ndvi_v5_2010.tif", "raster", None),
            ("/home/userx/Desktop/geoquery-update/data/esa_lc_2000.tif", "categorical_raster", esa_cmap)
        ]
        for d in data:
            cur.execute("""
                INSERT INTO datasets (path, type, info)
                VALUES (%s, %s, %s);
                """,
                (d[0], d[1], Jsonb(d[2]))
            )

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


def insert_dummy_extract_tasks(conn):
    with conn.cursor() as cur:
        data = [
            (1, 1, "zonal_stat_default", "mean", Jsonb({})),
            (1, 2, "zonal_stat_categorical", "categorical", Jsonb({}))
        ]
        for d in data:
            cur.execute("""
                INSERT INTO extract_tasks (fid, did, op, method, params)
                VALUES (%s, %s, %s, %s, %s);
                """,
                d
            )

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


if __name__ == "__main__":


    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            cur.execute("""DROP TABLE feature_geom""")
            cur.execute("""DROP TABLE feature_meta""")
            cur.execute("""DROP TABLE datasets""")
            cur.execute("""DROP TABLE extract_tasks""")
            cur.execute("""DROP TABLE extract_data""")


    # connect to PostgreSQL
    # TODO: configurable connection options, e.g. host and password
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:

        create_table_feature_geom(conn)
        create_table_feature_meta(conn)
        create_table_datasets(conn)
        create_table_extract_tasks(conn)
        create_table_extract_data(conn)


    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:

        insert_dummy_feature_geom(conn)
        insert_dummy_datasets(conn)
        # insert_dummy_extract_tasks(conn)



    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            x = cur.execute("""SELECT * FROM feature_geom""").fetchall()
            cur.execute("""SELECT * FROM feature_meta""").fetchall()
            cur.execute("""SELECT * FROM datasets""").fetchall()
            cur.execute("""SELECT * FROM extract_tasks""").fetchall()
            cur.execute("""SELECT * FROM extract_data""").fetchall()




"""
conn = psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432")
cur = conn.cursor()

cur.close()
conn.close()
"""
