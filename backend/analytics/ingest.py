"""
Ingest helpers for user-uploaded custom boundaries submitted with a data request.
Features are created via bulk_create to bypass Django signals intentionally.
"""
import json
import uuid

from django.contrib.gis.geos import GEOSGeometry

from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection


def ingest_custom_boundary(
    geojson_fc: dict,
    datasets: list[dict],
    contact: str,
    name: str | None,
    selection_label: str | None,
    selection_detail: str | None,
    upload_metadata: dict | None = None,
) -> tuple[Request, int, list[str]]:
    """
    Ingest a user-uploaded GeoJSON FeatureCollection and create a Request.

    Creates FeatureCollection, Feature, and FeatMap records with is_user_upload=True,
    then builds ExtractTasks directly from the selected datasets without coverage checks.

    Returns (request, task_count, warnings).
    Raises ValueError if no extract tasks can be created.
    """
    fc_uid = str(uuid.uuid4())

    fc = FeatureCollection.objects.create(
        name=f"user_upload_{fc_uid}",
        path=f"user_uploads/{fc_uid}",
        is_user_upload=True,
        active=True,
        public=False,
        upload_metadata=upload_metadata or {},
    )

    # bulk_create bypasses post_save signals — intentional for user uploads
    raw_features = geojson_fc.get("features") or []
    feature_objs = Feature.objects.bulk_create([
        Feature(shape=GEOSGeometry(json.dumps(f["geometry"])))
        for f in raw_features
    ])

    feat_map_objs = FeatMap.objects.bulk_create([
        FeatMap(
            fc=fc,
            geom=feature,
            name=(raw["properties"] or {}).get("name")
                 or (raw["properties"] or {}).get("NAME")
                 or None,
            attr=raw.get("properties") or None,
        )
        for feature, raw in zip(feature_objs, raw_features)
    ])

    all_task_ids: set[int] = set()
    warnings: list[str] = []
    valid_datasets: list[dict] = []

    for ds in datasets:
        dataset_name = (ds.get("datasetName") or "").strip()
        extract_types = ds.get("extractTypes") or []
        resources_filter = ds.get("resources") or []

        if not dataset_name:
            continue

        try:
            dataset_obj = Dataset.objects.get(name=dataset_name, active=True)
        except Dataset.DoesNotExist:
            warnings.append(f"Dataset '{dataset_name}' not found or inactive.")
            continue

        resource_qs = DatasetResource.objects.filter(dataset=dataset_obj)
        if resources_filter:
            resource_qs = resource_qs.filter(name__in=resources_filter)

        po_qs = ProcessingOption.objects.filter(dataset=dataset_obj, active=True, public=True)
        if extract_types:
            po_qs = po_qs.filter(short_name__in=extract_types)

        resources = list(resource_qs)
        pos = list(po_qs)

        if not resources or not pos:
            warnings.append(
                f"No resources or processing options found for dataset '{dataset_name}'."
            )
            continue

        ExtractTask.objects.bulk_create([
            ExtractTask(resource=resource, fm=fm, po=po)
            for fm in feat_map_objs
            for resource in resources
            for po in pos
        ], ignore_conflicts=True)

        task_ids = list(
            ExtractTask.objects.filter(
                fm__in=feat_map_objs,
                resource__dataset=dataset_obj,
            ).values_list("id", flat=True)
        )
        all_task_ids.update(task_ids)

        valid_datasets.append({
            "dataset_name": dataset_name,
            "dataset_type": (ds.get("datasetType") or "").strip() or None,
            "extract_types": extract_types,
            "resources": resources_filter,
            "resource_labels": ds.get("resourceLabels") or [],
        })

    if not all_task_ids:
        raise ValueError(
            "No extract tasks could be created for the submitted datasets."
        )

    feature_ids = [fm.geom_id for fm in feat_map_objs]

    req = Request.objects.create(
        contact=contact,
        custom_name=name or None,
        source="web_custom",
        status=-1,
        data={
            "selection_label": selection_label,
            "selection_detail": selection_detail,
            "feature_ids": feature_ids,
            "datasets": valid_datasets,
            "is_custom_boundary": True,
            "fc_id": fc.id,
        },
    )

    RequestMap.objects.bulk_create([
        RequestMap(request=req, task_id=task_id)
        for task_id in all_task_ids
    ])

    return req, len(all_task_ids), warnings
