from time import sleep
from pathlib import Path
from typing import Optional

import click
import psycopg
from psycopg.errors import UniqueViolation
import shapely
from tqdm import tqdm
import geopandas as gpd

from conn import get_conn

# function to insert row from geopandas df into boundaries table
def insert_feature(cur, dataset_id, adm_level, row) -> None:

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

def run_import(sample: Optional[int]=False) -> None:

    if sample and sample < 1:
        raise ValueError("sample must be a positive integer")

    dataset_name: str = "gbv6"

    # GeoPandas GeoSeries of group names to exclusively import
    # populated after init of first GeoDataFrame below
    # only used if sample is not None
    sampled_groups: gpd.GeoSeries = gpd.GeoSeries()

    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:

            try:
                # insert dataset name, get its associated id
                cur.execute("INSERT INTO datasets (name) VALUES (%s) RETURNING id", [dataset_name])
                dataset_id = cur.fetchone()[0]
            except UniqueViolation:
                raise UniqueViolation(f"dataset {dataset_name} already exists in database!")

            # for each ADM level file downloaded from geoBoundaries
            for adm_level in range(3):
                src = Path(f"geoBoundariesCGAZ_ADM{adm_level}.gpkg") 

                # load this file into a geopandas df
                print(f"Loading ADM{adm_level}...", end="")
                df: gpd.GeoDataFrame = gpd.read_file(src)
                print("done")

                if sample:
                    # if this is the first iteration, select groups to sample
                    if adm_level == 0:
                        selected_groups = df["shapeGroup"].unique()[:sample]

                    # filter df to only include selected groups
                    df = df[df["shapeGroup"].isin(selected_groups)]

                # iterate through rows of df
                # NOTE: there may be faster ways to iterate
                for row in tqdm(df.to_dict(orient="records")):
                    insert_feature(cur, dataset_id, adm_level, row)


@click.command()
@click.option('--sample', default=False, type=int)
def main(sample: bool) -> None:
    if sample:
        print(f"WARNING: Only importing a sample of {sample} countrys' boundaries for testing.")
    run_import(sample=sample)

if __name__ == "__main__":
    main()
