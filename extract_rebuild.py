from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
import shapely
import geopandas as gpd
import rasterstats as rs


def run_extract():
    """Main function to run an extraction of a dataset to a feature
    Contains the following steps:
    - get an extract task
    - prepare task components
    - send task to function to run necessary operation
    - receive and prepare results
    - export results
    """
    version = "0.0.1"
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            task = get_extract_task()
            feat = get_feat(task[1])
            data_path, data_type, data_info = get_data(task[2])
            func = get_func(task[3])
            method = task[4]

            op_kwargs = {"stat" : method}
            if method == "categorical":
                op_kwargs["category_map"] = dict(zip(data_info.values(), data_info.keys()))


            result = run_op(feat, data_path, func, **op_kwargs)

            formatted_results = format_output(result, **op_kwargs)
            for method, val in formatted_results:
                status = export_result(fid=task[1], did=task[2], op=task[3], method=method, clean_result=val, version=version)

            update_extract_task(task[0], 1, "complete")
            return status



def update_extract_task(task_id, status, update_type):
    """Update the status of an extract task"""
    if update_type not in ["update", "complete"]:
        raise ValueError(f"Update type {update_type} not supported.")
    update_str = f"{update_type}_time"
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            cur.execute(
                psycopg.sql.SQL("""
                UPDATE extract_tasks
                SET    status = %s, {} = CURRENT_TIMESTAMP
                WHERE  task_id = %s;
                """).format(psycopg.sql.Identifier(update_str)),
                (status, task_id))



def get_extract_task():
    """Retrieve an extract task"""
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            # GET TASK FROM EXTRACT TASK TABLE
            # task = cur.execute("""SELECT * FROM extract_tasks LIMIT 1""").fetchall()[0]

            query = """
            UPDATE extract_tasks
            SET    status = 2
            WHERE  task_id = (
                    SELECT task_id
                    FROM extract_tasks
                    WHERE status = 0
                    ORDER BY priority DESC, submit_time ASC
                    LIMIT  1
                    FOR UPDATE SKIP LOCKED
                    )
            RETURNING *;
            """
            task = cur.execute(query)
            task_result = task.fetchone()
            if task_result is None:
                raise ValueError("No available tasks.")
            return task_result


def get_feat(fid):
    """xxxxx"""
    # GET FEATURE FROM FEATURE TABLE
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            feat = cur.execute("""SELECT * FROM feature_geom WHERE fid = %s""", (fid,)).fetchall()[0]
    geom = shapely.wkb.loads(feat[1], hex=True)

    return geom


def get_data(did):
    """xxxxx"""
    # data = # GET DATA META FROM DATA TABLE AND ASSOCIATED PATH/INFO FOR ACTUAL DATASET
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            data = cur.execute("""SELECT * FROM datasets WHERE did = %s""", (did,)).fetchall()[0]
    path, type, info = data[1], data[2], data[3]
    return path, type, info


def get_func(op):
    """xxxxx"""
    if op == "zonal_stat_default":
        func = zonal_stat_default
    elif op == "zonal_stat_categorical":
        func = zonal_stat_categorical
    else:
        raise ValueError(f"Operation {op} not supportedx.")
    return func


def run_op(feat, data, func, **kwargs):
    results = func(feat, data, **kwargs)
    return results


def format_output(result, **kwargs):
    """xxxxx"""
    if kwargs["stat"] == "categorical":
        formatted_result = [(f"categorical_{k}", v) for k, v in result.items()]
    else:
        formatted_result = [(kwargs["stat"], result)]
    return formatted_result


def export_result(fid, did, op, method, clean_result, version, **kwargs):
    """EXPORT RESULT TO EXTRACT RESULT TABLE"""
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            status = insert_result(cur, version, fid, did, op, method, clean_result)
    return status


def insert_result(cur, version, fid, did, op, method, result):
    cur.execute("""
        INSERT INTO extract_data (fid, did, op, method, value, version)
        VALUES (%s, %s, %s, %s, %s, %s);
        """,
        (fid, did, op, method, result, version))


def zonal_stat_default(feat, raster, stat, **kwargs):
    """Default zonal stat function."""
    zs_output = rs.zonal_stats(feat, raster, stats=stat)
    return zs_output[0][stat]


def zonal_stat_categorical(feat, raster, category_map, **kwargs):
    """Default zonal stat function."""
    zs_output = rs.zonal_stats(feat, raster, categorical=True, category_map=category_map)
    return zs_output[0]


# ==============================================================================


def create_table_feature_geom(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feature_geom (
            fid        SERIAL PRIMARY KEY,
            geom       geometry NOT NULL
        );
    """)

def insert_dummy_feature_geom(cur):
    adm_level = 1
    print(f"Loading ADM{adm_level}...")
    src = Path(f"geoBoundariesCGAZ_ADM{adm_level}.gpkg")
    # load this file into a geopandas df
    df = gpd.read_file(src)
    # iterate through rows of df
    # NOTE: there may be faster ways to iterate
    for ix, row in enumerate(df.to_dict(orient="records")):
        insert_row(cur, row)
        if ix > 10:
            break

# function to insert row from geopandas df into boundaries table
def insert_row(cur, row):
    cur.execute("""
        INSERT INTO feature_geom (geom)
        VALUES (ST_GeomFromText(%s));
        """,
        ( shapely.to_wkt(row["geometry"]), )
    )

def create_table_datasets(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            did        SERIAL PRIMARY KEY,
            path       varchar(200),
            type       varchar(200),
            info       jsonb DEFAULT NULL
        );
    """)

def insert_dummy_datasets(cur):
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
        ("/home/userx/Desktop/postgis_test/avhrr_ndvi_v5_2010.tif", "raster", None),
        ("/home/userx/Desktop/postgis_test/esa_lc_2000.tif", "categorical_raster", esa_cmap)
    ]
    for d in data:
        cur.execute("""
            INSERT INTO datasets (path, type, info)
            VALUES (%s, %s, %s);
            """,
            (d[0], d[1], Jsonb(d[2]))
        )

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


def insert_dummy_extract_tasks(cur):
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
            cur.execute("""DROP TABLE datasets""")
            cur.execute("""DROP TABLE extract_tasks""")
            cur.execute("""DROP TABLE extract_data""")


    # connect to PostgreSQL
    # TODO: configurable connection options, e.g. host and password
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:

            create_table_feature_geom(cur)
            create_table_datasets(cur)
            create_table_extract_tasks(cur)
            create_table_extract_data(cur)

            insert_dummy_feature_geom(cur)
            insert_dummy_datasets(cur)
            insert_dummy_extract_tasks(cur)



    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            x = cur.execute("""SELECT * FROM feature_geom""").fetchall()
            cur.execute("""SELECT * FROM datasets""").fetchall()
            cur.execute("""SELECT * FROM extract_tasks""").fetchall()
            cur.execute("""SELECT * FROM extract_data""").fetchall()




"""
conn = psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432")
cur = conn.cursor()

cur.close()
conn.close()
"""
