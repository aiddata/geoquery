import shapely
import pandas as pd
import geopandas as gpd

from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ExtractTask, ExtractData, ProcessingOption

def merge_task_features(task_list):
    """merge processing task results for the given extrat task list
    """
    dict_list = []
    for task_id in task_list:

        task_item = ExtractTask.objects.filter(id=task_id).first()
        task_data = ExtractData.objects.filter(id=task_id)

        if task_item is None:
            raise Exception(f"ExtractTask with id {task_id} not found.")

        fm_item = FeatMap.objects.filter(id=task_item.fm_id).first()
        fc_name = FeatureCollection.objects.filter(id=fm_item.fc_id).first().name
        geom_id = fm_item.geom_id
        # get geometry for this geom_id as EWKT string (e.g. "SRID=4326;POINT(1 2)")
        django_geom = Feature.objects.filter(id=geom_id).first()
        geom = django_geom.shape

        row_dict = {
            "feature_collection": fc_name,
            "geom_id": geom_id,
            "geometry": geom,
        }
        dict_list.append(row_dict)


    if len(dict_list) == 0:
        return "Empty", None

    merged_gdf = pd.GeoDataFrame(dict_list)

    return "Success", merged_gdf


def merge_task_results(task_list):
    """merge processing task results for the given extrat task list
    """
    dict_list = []
    for task_id in task_list:

        task_item = ExtractTask.objects.filter(id=task_id).first()
        task_data = ExtractData.objects.filter(id=task_id)

        if task_item is None:
            raise Exception(f"ExtractTask with id {task_id} not found.")
        if task_data is None:
            raise Exception(f"ExtractData with id {task_id} not found.")


        fm_item = FeatMap.objects.filter(id=task_item.fm_id).first()
        fc_name = FeatureCollection.objects.filter(id=fm_item.fc_id).first().name
        geom_id = fm_item.geom_id
        dr_name = DatasetResource.objects.filter(id=task_item.resource_id).first().name

        for td in task_data:
            data_val = td[td.data_column]
            unique_col = f"{dr_name}.{td.name}"
            row_dict = {
                "feature_collection": fc_name,
                "geom_id": geom_id,
                unique_col: data_val
            }
            dict_list.append(row_dict)


    if len(dict_list) == 0:
        return "Empty", None

    merged_df = pd.DataFrame(dict_list)

    return "Success", merged_df
