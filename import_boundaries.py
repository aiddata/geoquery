from time import sleep
from pathlib import Path

import psycopg
import shapely
from tqdm import tqdm
import geopandas as gpd

from conn import get_conn

# function to insert row from geopandas df into boundaries table
def insert_feature(cur, dataset_id, adm_level, row):

    wkt = shapely.to_wkt(row["geometry"])
    
    # check if geom is already in features table, returning any matching ids
    cur.execute("""
        SELECT id FROM features WHERE ST_Equals(ST_GeomFromText(%s), shape)
    """,
    (wkt,))

    result = cur.fetchone()
    
    if result is None:
        cur.execute("""
            INSERT INTO features (shape) VALUES (ST_GeomFromText(%s)) RETURNING id;
            """,
            (wkt,))
        result = cur.fetchone()[0]
    else:
        # print("Found a matching geometry!")
        result = result[0]

    # insert into feat_map with that id
    cur.execute("""
        INSERT INTO feat_map (dataset_id, geom_id, name, grouping, level)
        VALUES (%s, %s, %s, %s, %s);
        """,
        (dataset_id, result, row["shapeName"], row["shapeGroup"], adm_level))


if __name__ == "__main__":
    dataset_name = "gbv6"

    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:

            cur.execute("INSERT INTO datasets (name) VALUES (%s) RETURNING id", [dataset_name])
            dataset_id = cur.fetchone()[0]

            vac_count = 0

            # for each ADM level file downloaded from geoBoundaries
            for adm_level in range(3):
                print(f"Loading ADM{adm_level}...")
                src = Path(f"geoBoundariesCGAZ_ADM{adm_level}.gpkg") 
                # load this file into a geopandas df
                df = gpd.read_file(src)
                # iterate through rows of df
                # NOTE: there may be faster ways to iterate
                for row in tqdm(df.to_dict(orient="records")):
                    if vac_count > 20:
                        # conn.commit()
                        # cur.execute("VACUUM ANALYZE features;")
                        vac_count = 0
                    insert_feature(cur, dataset_id, adm_level, row)
                    vac_count += 1
