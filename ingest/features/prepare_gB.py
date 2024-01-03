import json
from pathlib import Path
from typing import List, Optional
import concurrent.futures

from loguru import logger
import geopandas as gpd
import requests
import shapely
from psycopg.types.json import Json, Jsonb

from gqcore.utils.logs import get_logger
from gqcore.utils.ingest.ingest_feature_collection import ingest_feature_collection
from gqcore.utils.db import features as futils

get_logger("ingest")

logger.info(f"Starting geoBoundaries bulk ingest")

# set this to None to download all ISO3 boundaries
dl_iso3_list: Optional[List[str]] = ["AFG"]
# dl_iso3_list: Optional[List[str]] = None

target_gb_commit = "ff0d953b5aa2"

gb_dir = Path("/home/userx/Desktop/geoquery-update/data/geoBoundaries")

output_path = Path(
    f"/home/userx/Desktop/geoquery-update/data/geoBoundaries/processed/v6_{target_gb_commit}"
)
output_path.mkdir(exist_ok=True, parents=True)

default_meta = {
    "active": 0,
    "public": 0,
    "name": None,
    "path": None,
    "file_extension": ".gpkg",
    "title": None,
    "description": None,
    "details": "",
    "tags": ["geoboundaries", "administrative", "boundary"],
    "citation": "Runfola, D. et al. (2020) geoBoundaries: A global database of political administrative boundaries. PLoS ONE 15(4): e0231866. https://doi.org/10.1371/journal.pone.0231866",
    "source_name": "geoBoundaries",
    "source_url": "geoboundaries.org",
    "other": {},
    "ingest_src": "geoquery_automated",
    "is_global": False,
    "group_name": None,
    "group_title": None,
    "group_class": None,
    "group_level": None,
}

gb_url = "https://www.geoboundaries.org/api"


def get_api_url(url):
    response = requests.get(url)
    content = response.json()
    return content


base_api_data = get_api_url(gb_url)

gb_iso3_list = [ i["ISO"] for i in base_api_data ]

if dl_iso3_list is None:
    iso3_list = set(gb_iso3_list)
else:
    iso3_list = set(gb_iso3_list).intersection(set(dl_iso3_list))

iso3_list = sorted(list(iso3_list))



ingest_items = []
for iso3 in iso3_list:
    api_url = f"{gb_url}/current/gbOpen/{iso3}/ALL/"
    try:
        iso3_items = get_api_url(api_url)
    except:
        logger.debug(f"Failed to get {api_url}")
    for item in iso3_items:
        #if item["boundaryType"] == "ADM2":
            #continue
        ingest_items.append(item)


def ingest_gb_item(item: dict):

    iso3 = item["boundaryISO"]

    adm_meta = default_meta.copy()

    adm_meta["name"] = f"gB_v6_{iso3}_{item['boundaryType']}"

    logger.info(f"Processing geoBoundaries item: {adm_meta['name']}")

    adm_meta[
        "title"
    ] = f"geoBoundaries v6 - {item['boundaryName']} {item['boundaryType']}"
    adm_meta[
        "description"
    ] = f"This feature collection represents the {item['boundaryType']} level boundaries for {item['boundaryName']} ({iso3}) from geoBoundaries v6."
    adm_meta["details"] = ""
    adm_meta["group_name"] = f"gb_v6_{iso3}"
    adm_meta["group_title"] = f"gB v6 - {iso3}"
    adm_meta["group_class"] = (
        "parent" if item["boundaryType"] == "ADM0" else "child"
    )
    adm_meta["group_level"] = int(item["boundaryType"][3:])

    # save full metadata from geoboundaries api to the "other" field
    adm_meta["other"] = item.copy()

    raw_dl_url = item["gjDownloadURL"]
    # "https://github.com/wmgeolab/geoBoundaries/raw/c0ed7b8/releaseData/gbOpen/AFG/ADM0/geoBoundaries-AFG-ADM0.geojson",

    commit_dl_url = raw_dl_url.replace(raw_dl_url.split("/")[6], target_gb_commit)

    gpkg_path = output_path / f"{Path(commit_dl_url).stem}.gpkg"
    adm_meta["path"] = str(gpkg_path)

    logger.debug(f"Downloading {commit_dl_url}")
    try:
        gdf = gpd.read_file(commit_dl_url)
    except:
        if requests.get(commit_dl_url).status_code == 404:
            logger.error(f"404: {commit_dl_url}")
            return
        else:
            try:
                raw_json = get_api_url(commit_dl_url)
                gdf = gpd.GeoDataFrame.from_features(raw_json["features"])
            except:
                logger.error(f"Failed to download {commit_dl_url}")
                return


    if "shapeName" not in gdf.columns:
        potential_name_field = f'{item["boundaryType"]}_NAME'
        if potential_name_field in gdf.columns:
            gdf["shapeName"] = gdf[potential_name_field]
        else:
            gdf["shapeName"] = None

    gdf.to_file(gpkg_path, driver="GPKG")

    logger.debug(f"Getting bounding box for {commit_dl_url}")
    spatial_extent = shapely.box(*gdf.total_bounds).wkt
    adm_meta["spatial_extent"] = spatial_extent

    logger.debug(f"Preparing features for {commit_dl_url}")
    feature_list = []
    for ix, row in gdf.iterrows():
        feature_list.append(
            futils.Feature(
                geometry=row.geometry.wkt,
                name=row["shapeName"],
                attr=row.drop(["geometry"]).to_dict(),
                parent=None,
            )
        )
    adm_meta["features"] = feature_list

    # export to json
    export_adm_meta = adm_meta.copy()
    export_adm_meta["features"] = None
    json_path = gpkg_path.with_suffix(".json")
    with open(json_path, "w") as file:
        json.dump(export_adm_meta, file, indent=4)

    # FC = futils.FeatureCollection(**adm_meta)
    # futils.insert_feature_collection(FC)
    # # futils.update_feature_collection(FC)

    ingest_feature_collection(json_data=adm_meta, update_or_insert=True)


if __name__ == "__main__":
    # for item in ingest_items:
    #     ingest_gb_item(item)

    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = [executor.submit(ingest_gb_item, item) for item in ingest_items]

        e = []
        for result in concurrent.futures.as_completed(futures):
            if result.exception() is not None:
                e.append(result.exception())

        if len(e) > 0:
            logger.error(f"{len(e)} exceptions occurred")
            unique_e = set([str(x) for x in e])
            logger.error(f"{len(unique_e)} unique exceptions occurred:")
            logger.error(f"Unique exceptions: {unique_e}")
            logger.exception(e[0])
