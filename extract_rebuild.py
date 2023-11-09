
import psycopg
import shapely
import rasterstats as rs
from psycopg.types.json import Jsonb

def build_extract_tasks():
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT fid FROM feature_geom""")
            fid_list = [i[0] for i in cur.fetchall()]
            cur.execute("""SELECT * FROM datasets""")
            datasets = cur.fetchall()
            for fid in fid_list:
                for data in datasets:
                    if data[2] == "raster":
                        op = "zonal_stat_default"
                        method_list = ["min", "max", "mean", "count"]
                        params = {}
                    elif data[2] == "categorical":
                        op = "zonal_stat_categorical"
                        method_list = ["categorical"]
                        params = data[5]

                    for method in method_list:
                        cur.execute("""
                            INSERT INTO extract_tasks (fid, did, op, method, params)
                            VALUES (%s, %s, %s, %s, %s)""",
                            (fid, data[0], op, method, Jsonb(params))
                        )

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
    """GET FEATURE FROM FEATURE TABLE"""
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            feat = cur.execute("""SELECT * FROM feature_geom WHERE fid = %s""", (fid,)).fetchall()[0]
    geom = shapely.wkb.loads(feat[1], hex=True)

    return geom


def get_data(did):
    """GET DATA META FROM DATA TABLE AND ASSOCIATED PATH/INFO FOR ACTUAL DATASET"""
    with psycopg.connect("postgresql://postgres:mysecretpassword@localhost:5432") as conn:
        with conn.cursor() as cur:
            data = cur.execute("""SELECT * FROM datasets WHERE did = %s""", (did,)).fetchall()[0]
    path, type, info = data[1], data[2], data[3]
    return path, type, info


def get_func(op):
    """Get appropriate function for operation."""
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
    """Format output data to be exported to extract_data table."""
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
