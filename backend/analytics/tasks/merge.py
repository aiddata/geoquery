from collections import defaultdict

import shapely
import pandas as pd
import geopandas as gpd

from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ExtractTask, ExtractData, ProcessingOption


def _group_by_dataset(task_map):
    """Invert a {task_id: dataset_id} map into {dataset_id: [task_id, ...]}.

    extract_tasks and extract_data are both LIST partitioned on dataset_id
    with PRIMARY KEY (dataset_id, id). id is the second PK column, so a
    filter on id alone can't seek the index and scans every partition --
    every query in this module goes one dataset at a time to stay pruned.
    """
    grouped = defaultdict(list)
    for task_id, dataset_id in task_map.items():
        grouped[dataset_id].append(task_id)
    return grouped


# How many tasks' rows are prefetched at once. Bounds peak memory for the
# large requests that exist in production (61k tasks) while still cutting the
# round trips by three orders of magnitude -- the whole point of batching
# here is round trips, not query time.
MERGE_CHUNK_SIZE = 1000


class _MergeLookups:
    """Batched stand-ins for the per-task queries this module used to run.

    The merge issued five queries per task (ExtractTask, ExtractData, FeatMap,
    FeatureCollection, DatasetResource). Each is ~0.1ms against its index, so
    the queries were never the cost -- the round trips were. A 1040-task
    request measured 3h38m here, ~2.5s per round trip, because every one of
    them queued for a pooler server slot.

    Feature collections and dataset resources are cached for the whole merge
    rather than per chunk: there are a handful of each no matter how many
    tasks reference them.
    """

    def __init__(self):
        self.fc_names = {}
        self.resources = {}

    def load(self, chunk):
        """Fetch what one chunk of ``(task_id, dataset_id)`` pairs needs.

        Returns ``(tasks, data_by_task, featmaps)``.
        """
        by_dataset = defaultdict(list)
        for task_id, dataset_id in chunk:
            by_dataset[dataset_id].append(task_id)

        tasks = {}
        data_by_task = defaultdict(list)
        for dataset_id, ds_task_ids in by_dataset.items():
            # dataset_id is required on both lookups, not just nice to have:
            # extract_tasks/extract_data are LIST partitioned on dataset_id
            # with PRIMARY KEY (dataset_id, id), so filtering on id alone
            # can't seek the PK index (id is its second column) and scans
            # every partition.
            for task in ExtractTask.objects.filter(
                dataset_id=dataset_id, id__in=ds_task_ids
            ):
                tasks[task.id] = task
            for row in ExtractData.objects.filter(
                dataset_id=dataset_id, extract_task_id__in=ds_task_ids
            ):
                data_by_task[row.extract_task_id].append(row)

        featmaps = {
            fm.id: fm
            for fm in FeatMap.objects.filter(
                id__in={task.fm_id for task in tasks.values()}
            )
        }

        missing_fcs = {fm.fc_id for fm in featmaps.values()} - self.fc_names.keys()
        if missing_fcs:
            self.fc_names.update(
                FeatureCollection.objects.filter(id__in=missing_fcs).values_list(
                    "id", "name"
                )
            )

        missing_resources = {
            resource_id
            for task in tasks.values()
            for resource_id in task.resource_ids
        } - self.resources.keys()
        if missing_resources:
            self.resources.update(
                {
                    resource.id: resource
                    for resource in DatasetResource.objects.filter(
                        id__in=missing_resources
                    )
                }
            )

        return tasks, data_by_task, featmaps


def _chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def merge_task_features(task_map):
    """build a GeoDataFrame of unique features covered by the given
    {task_id: dataset_id} mapping"""
    fm_ids = set()
    for dataset_id, ds_task_ids in _group_by_dataset(task_map).items():
        fm_ids.update(
            ExtractTask.objects.filter(dataset_id=dataset_id, id__in=ds_task_ids)
            .values_list("fm_id", flat=True)
            .distinct()
        )

    dict_list = []
    fc_names = {}
    # Sorted so the chunking below is deterministic; the set this replaces
    # gave an arbitrary (if stable-per-run) order, and nothing downstream
    # depends on which one.
    for chunk in _chunked(sorted(fm_ids), MERGE_CHUNK_SIZE):
        featmaps = {fm.id: fm for fm in FeatMap.objects.filter(id__in=chunk)}

        missing_fcs = {fm.fc_id for fm in featmaps.values()} - fc_names.keys()
        if missing_fcs:
            fc_names.update(
                FeatureCollection.objects.filter(id__in=missing_fcs).values_list(
                    "id", "name"
                )
            )

        geoms = {
            feature.id: feature
            for feature in Feature.objects.filter(
                id__in={fm.geom_id for fm in featmaps.values()}
            )
        }

        for fm_id in chunk:
            fm_item = featmaps[fm_id]
            geom_id = fm_item.geom_id
            dict_list.append(
                {
                    "feature_collection": fc_names[fm_item.fc_id],
                    "geom_id": geom_id,
                    "geometry": shapely.from_wkb(bytes(geoms[geom_id].shape.wkb)),
                }
            )

    if not dict_list:
        return "Empty", None

    merged_gdf = gpd.GeoDataFrame(dict_list, geometry="geometry", crs="EPSG:4326")

    return "Success", merged_gdf


def merge_task_results(task_map):
    """merge processing task results for the given {task_id: dataset_id} mapping"""
    rows = {}
    lookups = _MergeLookups()
    # Materialised so the chunks below preserve task_map's order: `rows` is
    # insertion-ordered and becomes the DataFrame's row order.
    items = list(task_map.items())

    for chunk in _chunked(items, MERGE_CHUNK_SIZE):
        tasks, data_by_task, featmaps = lookups.load(chunk)

        for task_id, dataset_id in chunk:
            task_item = tasks.get(task_id)
            task_data = data_by_task.get(task_id, [])

            if task_item is None:
                raise Exception(f"ExtractTask with id {task_id} not found.")

            fm_item = featmaps.get(task_item.fm_id)
            fc_name = lookups.fc_names[fm_item.fc_id]
            geom_id = fm_item.geom_id

            # The prefetch returns resources in no particular order, so they
            # must be re-ordered against task_item.resource_ids by dict
            # lookup -- same reindex pattern _run_extract_task uses
            # (processing.py): position i here has to line up with position i
            # in every ExtractData row's value arrays for this task (see
            # ExtractTask/ExtractData docstrings).
            resources = [
                lookups.resources[rid] for rid in task_item.resource_ids
            ]

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
