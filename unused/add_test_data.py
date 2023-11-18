from pathlib import Path
from typing import List

import psycopg
from psycopg.types.json import Jsonb

from utils.conn import get_conn


def insert_dummy_datasets(conn):
    with conn.cursor() as cur:
        esa_cmap = {
            "urban": 190,
            "bare_areas": 200,
            "sparse_vegetation": 140,
            "snow_ice": 220,
            "shrubland": 120,
            "no_data": 0,
            "mosaic_cropland": 30,
            "rainfed_cropland": 10,
            "wetland": 180,
            "forest": 50,
            "grassland": 110,
            "water_bodies": 210,
            "irrigated_cropland": 20,
        }
        data = [
            (
                Path("avhrr_ndvi_v5_2010.tif"),
                "raster",
                None,
            ),
            (
                Path("esa_lc_2000.tif"),
                "categorical_raster",
                esa_cmap,
            ),
        ]
        for d in data:
            cur.execute(
                """
                INSERT INTO datasets (path, type, info)
                VALUES (%s, %s, %s);
                """,
                (d[0].as_posix(), d[1], Jsonb(d[2])),
            )


def insert_dummy_extract_tasks(conn):
    with conn.cursor() as cur:
        data = [
            (1, 1, "zonal_stat_default", "mean", Jsonb({})),
            (1, 2, "zonal_stat_categorical", "categorical", Jsonb({})),
        ]
        for d in data:
            cur.execute(
                """
                INSERT INTO extract_tasks (fid, did, op, method, params)
                VALUES (%s, %s, %s, %s, %s);
                """,
                d,
            )


def insert_dummy_data():
    with get_conn() as conn:
        insert_dummy_feature_geom(conn)
        insert_dummy_datasets(conn)
        # insert_dummy_extract_tasks(conn)


if __name__ == "__main__":
    insert_dummy_data()


from utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""SELECT * FROM coverage""").fetchall()

from utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""SELECT * FROM extract_tasks""").fetchall()
        cur.execute("""SELECT * FROM extract_data""").fetchall()


from utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        x = cur.execute("""SELECT * FROM feature_collections""").fetchall()
        y = cur.execute("""SELECT * FROM features""").fetchall()
        z = cur.execute("""SELECT * FROM feat_map""").fetchall()
        print('feature_collections', len(x), x)
        print('features', len(y), y)
        print('feat_map', len(z), z)

from utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        x = cur.execute("""SELECT * FROM datasets""").fetchall()
        y = cur.execute("""SELECT * FROM mappings""").fetchall()
        z = cur.execute("""SELECT * FROM processing_options""").fetchall()
        print('datasets', len(x), x)
        print('mappings', len(y), y)
        print('processing_options', len(z), z)
        w = cur.execute("""SELECT * FROM dataset_resources""").fetchall()
        print('dataset_resources', len(w), w)
