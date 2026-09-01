"""
Ingest helpers for user-uploaded custom boundaries submitted with a data request.
Features are created via bulk_create to bypass Django signals intentionally.
"""

import json
import uuid

from django.contrib.gis.geos import GEOSGeometry

from analytics.models import ExtractTask, Request, RequestMap
from catalog.access import visible_datasets, visible_processing_options_for_dataset
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection


def ingest_custom_boundary(
    geojson_fc: dict,
    datasets: list[dict],
    req: "Request",
    user=None,
) -> tuple[int, list[str]]:
    """
    Ingest a user-uploaded GeoJSON FeatureCollection into an existing Request.

    Creates FeatureCollection, Feature, and FeatMap records with is_user_upload=True,
    then builds ExtractTasks directly from the selected datasets without coverage checks.
    Updates req.data with the ingested feature IDs and fc_id, and sets req.status = -1.

    Returns (task_count, warnings).
    Raises ValueError if no extract tasks can be created.
    """
    fc_uid = str(uuid.uuid4())

    upload_metadata = req.data.get("upload_metadata") or {}

    fc = FeatureCollection.objects.create(
        name=f"user_upload_{fc_uid}",
        path=f"user_uploads/{fc_uid}",
        is_user_upload=True,
        active=True,
        public=False,
        upload_metadata=upload_metadata,
    )

    # bulk_create bypasses post_save signals — intentional for user uploads
    raw_features = geojson_fc.get("features") or []
    valid_raw: list[dict] = []
    feature_objs_list: list[Feature] = []
    warnings: list[str] = []
    skipped = 0
    for f in raw_features:
        geom = f.get("geometry")
        if not geom:
            skipped += 1
            continue
        try:
            shape = GEOSGeometry(json.dumps(geom))
        except Exception:
            skipped += 1
            continue
        valid_raw.append(f)
        feature_objs_list.append(Feature(shape=shape))

    if skipped:
        warnings.append(
            f"{skipped} feature(s) skipped due to null or invalid geometry."
        )

    feature_objs = Feature.objects.bulk_create(feature_objs_list)

    feat_map_objs = FeatMap.objects.bulk_create(
        [
            FeatMap(
                fc=fc,
                geom=feature,
                name=(raw["properties"] or {}).get("name")
                or (raw["properties"] or {}).get("NAME")
                or None,
                attr=raw.get("properties") or None,
            )
            for feature, raw in zip(feature_objs, valid_raw)
        ]
    )

    all_task_ids: set[int] = set()
    valid_datasets: list[dict] = []

    for ds in datasets:
        dataset_name = (ds.get("datasetName") or "").strip()
        extract_types = ds.get("extractTypes") or []
        resources_filter = ds.get("resources") or []
        task_kwargs = ds.get("kwargs") or None

        if not dataset_name:
            continue

        # `user` is the submitter (None when anonymous), threaded in from
        # RequestView.post. Custom-boundary submissions are gated the same way
        # as standard ones.
        try:
            dataset_obj = visible_datasets(user).get(name=dataset_name)
        except Dataset.DoesNotExist:
            warnings.append(f"Dataset '{dataset_name}' not found or not available.")
            continue

        resource_qs = DatasetResource.objects.filter(dataset=dataset_obj)
        if resources_filter:
            resource_qs = resource_qs.filter(name__in=resources_filter)

        po_qs = visible_processing_options_for_dataset(user, dataset_obj)
        if extract_types:
            po_qs = po_qs.filter(short_name__in=extract_types)

        resources = list(resource_qs)
        pos = list(po_qs)

        if not resources or not pos:
            warnings.append(
                f"No resources or processing options found for dataset '{dataset_name}'."
            )
            continue

        ExtractTask.objects.bulk_create(
            [
                ExtractTask(
                    resource=resource, fm=fm, po=po, kwargs=task_kwargs, priority=1
                )
                for fm in feat_map_objs
                for resource in resources
                for po in pos
            ],
            ignore_conflicts=True,
        )

        task_ids = list(
            ExtractTask.objects.filter(
                fm__in=feat_map_objs,
                resource__dataset=dataset_obj,
            ).values_list("id", flat=True)
        )
        all_task_ids.update(task_ids)

        valid_datasets.append(
            {
                "dataset_name": dataset_name,
                "dataset_type": (ds.get("datasetType") or "").strip() or None,
                "extract_types": extract_types,
                "resources": resources_filter,
                "resource_labels": ds.get("resourceLabels") or [],
                "kwargs": task_kwargs,
            }
        )

    if not all_task_ids:
        raise ValueError(
            "No extract tasks could be created for the submitted datasets."
        )

    feature_ids = [fm.geom_id for fm in feat_map_objs]

    req.data = {
        **req.data,
        "feature_ids": feature_ids,
        "datasets": valid_datasets,
        "fc_id": fc.id,
    }
    req.status = -1
    req.save(update_fields=["data", "status"])

    RequestMap.objects.bulk_create(
        [RequestMap(request=req, task_id=task_id) for task_id in all_task_ids]
    )

    return len(all_task_ids), warnings
