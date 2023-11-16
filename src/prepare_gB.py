import requests
from pathlib import Path
import json

import requests
import geopandas as gpd
from psycopg.types.json import Jsonb, Json

from utils.db import features as futils

dl_iso3_list = ["AFG"]

target_gb_commit = "ff0d953b5aa2"

gb_dir = Path("/home/userx/Desktop/geoquery-update/data/geoBoundaries")

output_path = Path(f"/home/userx/Desktop/geoquery-update/data/geoBoundaries/processed/v6_{target_gb_commit}")
output_path.mkdir(exist_ok=True, parents=True)

default_meta = {
    "active": 0,
    "public": 0,
    "name": None,
    "type": "boundary",
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
    "group_level": None
}

gb_url = "https://www.geoboundaries.org/api"

def get_api_url(url):
    response = requests.get(url)
    content = response.json()
    return content

base_api_data = get_api_url(gb_url)

gb_iso3_list = [i["ISO"] for i in base_api_data if "openAvailable" in i and i["openAvailable"]]

for iso3 in set(gb_iso3_list).intersection(set(dl_iso3_list)):
    api_url = f"{gb_url}/current/gbOpen/{iso3}/ALL/"
    iso3_items = get_api_url(api_url)
    for item in iso3_items:

        adm_meta = default_meta.copy()

        # save full metadata from geoboundaries api to the "other" field
        adm_meta["other"] = item.copy()

        adm_meta["name"] = f"gB_v6_{iso3}_{item['boundaryType']}"
        adm_meta["title"] = f"geoBoundaries v6 - {item['boundaryName']} {item['boundaryType']}"
        adm_meta["description"] = f"This feature collection represents the {item['boundaryType']} level boundaries for {item['boundaryName']} ({iso3}) from geoBoundaries v6."
        adm_meta["details"] = ""
        adm_meta["group_name"] = f"gb_v6_{iso3}"
        adm_meta["group_title"] = f"gB v6 - {iso3}"
        adm_meta["group_class"] = "parent" if item['boundaryType'] == "ADM0" else "child"
        adm_meta["group_level"] = int(item['boundaryType'][3:])

        raw_dl_url = item["gjDownloadURL"]
        # "https://github.com/wmgeolab/geoBoundaries/raw/c0ed7b8/releaseData/gbOpen/AFG/ADM0/geoBoundaries-AFG-ADM0.geojson",

        commit_dl_url = raw_dl_url.replace(raw_dl_url.split("/")[6], target_gb_commit)

        gpkg_path = output_path / f"{Path(commit_dl_url).stem}.gpkg"
        adm_meta["path"] = str(gpkg_path)

        gdf = gpd.read_file(commit_dl_url)
        gdf.to_file(gpkg_path, driver="GPKG")

        feature_list = []
        for ix, row in gdf.iterrows():
            feature_list.append(
                futils.Feature(
                    geometry=row.geometry.wkt,
                    name=row["shapeName"],
                    attr=row.drop(["geometry"]).to_dict(),
                    parent=None
                )
            )
        adm_meta["features"] = feature_list

        # export to json
        json_path = gpkg_path.with_suffix(".json")
        with open(json_path, "w") as file:
            json.dump(adm_meta, file, indent=4)


        FC = futils.FeatureCollection(**adm_meta)

        futils.insert_feature_collection(FC)

        # futils.update_feature_collection(FC)
