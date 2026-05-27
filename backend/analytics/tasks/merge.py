import shapely
import pandas as pd
import geopandas as gpd

from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ExtractTask, ExtractData, ProcessingOption

def merge_task_features(task_list):
    """build a GeoDataFrame of unique features covered by the given extract tasks
    """
    fm_ids = (
        ExtractTask.objects.filter(id__in=task_list)
        .values_list("fm_id", flat=True)
        .distinct()
    )

    dict_list = []
    for fm_id in fm_ids:
        fm_item = FeatMap.objects.filter(id=fm_id).first()
        fc_name = FeatureCollection.objects.filter(id=fm_item.fc_id).first().name
        geom_id = fm_item.geom_id
        django_geom = Feature.objects.filter(id=geom_id).first()
        geom = shapely.from_wkb(bytes(django_geom.shape.wkb))

        dict_list.append({
            "feature_collection": fc_name,
            "geom_id": geom_id,
            "geometry": geom,
        })

    if not dict_list:
        return "Empty", None

    merged_gdf = gpd.GeoDataFrame(dict_list, geometry="geometry", crs="EPSG:4326")

    return "Success", merged_gdf


def merge_task_results(task_list):
    """merge processing task results for the given extract task list
    """
    rows = {}
    for task_id in task_list:

        task_item = ExtractTask.objects.filter(id=task_id).first()
        task_data = ExtractData.objects.filter(extract_task_id=task_id)

        if task_item is None:
            raise Exception(f"ExtractTask with id {task_id} not found.")

        fm_item = FeatMap.objects.filter(id=task_item.fm_id).first()
        fc_name = FeatureCollection.objects.filter(id=fm_item.fc_id).first().name
        geom_id = fm_item.geom_id
        dr_name = DatasetResource.objects.filter(id=task_item.resource_id).first().name

        key = (fc_name, geom_id)
        if key not in rows:
            rows[key] = {"feature_collection": fc_name, "geom_id": geom_id}

        for td in task_data:
            if td.data_column == "int":
                data_val = int(td.int_value)
            elif td.data_column == "float":
                data_val = float(td.float_value)
            elif td.data_column == "str":
                data_val = td.str_value
            else:
                raise Exception(f"Unsupported data column type: {td.data_column}")
            rows[key][f"{dr_name}.{td.name}"] = data_val

    if not rows:
        return "Empty", None

    merged_df = pd.DataFrame(list(rows.values()))

    return "Success", merged_df
