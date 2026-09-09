import shapely
import pandas as pd
import geopandas as gpd

from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ExtractTask, ExtractData, ProcessingOption


def merge_task_features(task_list):
    """build a GeoDataFrame of unique features covered by the given extract tasks"""
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

        dict_list.append(
            {
                "feature_collection": fc_name,
                "geom_id": geom_id,
                "geometry": geom,
            }
        )

    if not dict_list:
        return "Empty", None

    merged_gdf = gpd.GeoDataFrame(dict_list, geometry="geometry", crs="EPSG:4326")

    return "Success", merged_gdf


def merge_task_results(task_list):
    """merge processing task results for the given extract task list"""
    rows = {}
    for task_id in task_list:
        task_item = ExtractTask.objects.filter(id=task_id).first()
        task_data = ExtractData.objects.filter(extract_task_id=task_id)

        if task_item is None:
            raise Exception(f"ExtractTask with id {task_id} not found.")

        fm_item = FeatMap.objects.filter(id=task_item.fm_id).first()
        fc_name = FeatureCollection.objects.filter(id=fm_item.fc_id).first().name
        geom_id = fm_item.geom_id

        # id__in does not preserve input order, so resources must be
        # re-ordered against task_item.resource_ids by dict lookup -- same
        # reindex pattern _run_extract_task uses (processing.py): position i
        # here has to line up with position i in every ExtractData row's
        # value arrays for this task (see ExtractTask/ExtractData docstrings).
        resources_by_id = {
            r.id: r
            for r in DatasetResource.objects.filter(id__in=task_item.resource_ids)
        }
        resources = [resources_by_id[rid] for rid in task_item.resource_ids]

        # Feature datasets (single GPKG, no file mask) get resource name
        # "{dataset}_none". Substitute the outcome field from task kwargs so
        # the CSV column reads "acled_event_count.*" instead of "acled_none.*".
        # Computed independently per resource -- in a grouped task, each
        # position may or may not end in "_none" regardless of the others.
        dr_names = []
        for resource in resources:
            dr_name = resource.name
            if (
                dr_name.endswith("_none")
                and task_item.kwargs
                and "outcome" in task_item.kwargs
            ):
                dr_name = f"{dr_name[:-5]}_{task_item.kwargs['outcome']}"
            dr_names.append(dr_name)

        key = (fc_name, geom_id)
        if key not in rows:
            row_base = {"feature_collection": fc_name, "geom_id": geom_id}
            if fm_item.attr:
                for attr_key, attr_val in fm_item.attr.items():
                    row_base[f"boundary.{attr_key}"] = attr_val
            rows[key] = row_base

        for td in task_data:
            if td.data_column == "int":
                values, coerce = td.int_values, int
            elif td.data_column == "float":
                values, coerce = td.float_values, float
            elif td.data_column == "str":
                values, coerce = td.str_values, str
            else:
                raise Exception(f"Unsupported data column type: {td.data_column}")

            values = values or []
            for i, dr_name in enumerate(dr_names):
                # A None at position i means resource_ids[i]'s result wasn't
                # computed for this task (failed, or not yet processed) --
                # see ExtractData's docstring. That's expected, not an error:
                # skip it entirely rather than writing a placeholder, so the
                # resulting uneven row set becomes a genuine NaN (not a
                # fabricated one) when pd.DataFrame assembles rows below.
                if i >= len(values) or values[i] is None:
                    continue
                rows[key][f"{dr_name}.{td.name}"] = coerce(values[i])

    if not rows:
        return "Empty", None

    merged_df = pd.DataFrame(list(rows.values()))

    return "Success", merged_df
