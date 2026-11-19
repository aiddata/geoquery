"""A past request as a request recipe (GEO-126): what "Use as template" loads.

The recipe has the frontend's shape (frontend/src/lib/recipe.ts):
``{"v": 1, "boundaries": {"fcIds", "featureIds"}, "datasets": [cart items]}``.
It is checked against the catalog as the viewer sees it now. Whatever no
longer applies (a dataset that's gone or doesn't cover these boundaries, a
period or measure that's been removed, features that weren't a whole boundary
set) is left out and listed, so the page can say what was dropped.
"""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Count

from analytics.coverage import valid_coverage
from catalog.access import (
    visible_datasets,
    visible_feature_collections,
    visible_processing_options_for_dataset,
)
from datasets.models import DatasetResource
from features.models import FeatMap

RECIPE_VERSION = 1


def _fc_ref(fc) -> dict:
    return {
        "id": fc.id,
        "name": fc.name,
        "title": fc.title,
        "short_name": fc.short_name,
        "bbox": list(fc.spatial_extent.extent) if fc.spatial_extent else None,
    }


def _boundaries(user, req_data: dict):
    """(boundary sets, featureIds, dropped feature count) for a request.

    New requests record the boundary sets that were picked (``fc_ids``). For
    older ones they're worked out from ``feature_ids``: a visible set whose
    features are all in the request counts as picked. If no set is whole and
    the features all come from one set, it's that set narrowed to them.
    Features left over are dropped.
    """
    feature_ids = [i for i in req_data.get("feature_ids") or [] if isinstance(i, int)]
    if not feature_ids:
        return [], [], 0
    wanted = set(feature_ids)
    visible = visible_feature_collections(user)

    # Selected features in each visible set that has any
    matched: dict[int, set[int]] = defaultdict(set)
    for fc_id, geom_id in FeatMap.objects.filter(
        geom_id__in=feature_ids, fc__in=visible
    ).values_list("fc_id", "geom_id"):
        matched[fc_id].add(geom_id)
    totals = dict(
        FeatMap.objects.filter(fc_id__in=matched)
        .values("fc_id")
        .annotate(n=Count("id"))
        .values_list("fc_id", "n")
    )
    fcs = {fc.id: fc for fc in visible.filter(id__in=matched)}

    recorded = [i for i in req_data.get("fc_ids") or [] if isinstance(i, int)]
    if recorded:
        picked = [i for i in recorded if i in fcs]
        if len(picked) == 1 and len(recorded) == 1:
            fc_id = picked[0]
            ids = matched[fc_id]
            narrowed = [] if len(ids) == totals.get(fc_id) else sorted(ids)
            return [fcs[fc_id]], narrowed, len(wanted - ids)
        covered = set().union(*(matched[i] for i in picked)) if picked else set()
        return [fcs[i] for i in picked], [], len(wanted - covered)

    whole = [i for i in matched if len(matched[i]) == totals.get(i)]
    # A small set that sits inside a bigger whole one wasn't picked by itself
    whole = [
        i
        for i in whole
        if not any(j != i and matched[i] < matched[j] for j in whole)
    ]
    if whole:
        whole.sort(key=lambda i: (fcs[i].title or fcs[i].name).lower())
        covered = set().union(*(matched[i] for i in whole))
        return [fcs[i] for i in whole], [], len(wanted - covered)
    if len(matched) == 1:
        fc_id = next(iter(matched))
        return [fcs[fc_id]], sorted(matched[fc_id]), len(wanted - matched[fc_id])
    return [], [], len(wanted)


def _filter_selections(kwargs: dict) -> dict:
    """The Customize filters a feature dataset's kwargs were built from."""
    selections = {}
    for key, value in kwargs.items():
        if key == "outcome" or not isinstance(value, dict):
            continue
        selections[key] = {k: v for k, v in value.items() if k != "aggregate"}
    return selections


def request_recipe(user, req) -> dict:
    """The recipe for a past (standard-boundary) request, plus the boundary
    sets it names and what was dropped from it."""
    req_data = req.data or {}
    fcs, feature_ids, dropped_features = _boundaries(user, req_data)
    # Coverage is checked on the features the recipe keeps
    kept_features = (
        feature_ids
        if feature_ids
        else list(
            FeatMap.objects.filter(fc_id__in=[fc.id for fc in fcs]).values_list(
                "geom_id", flat=True
            )
        )
    )

    datasets: list[dict] = []
    dropped_datasets: list[dict] = []
    dropped_options: list[dict] = []

    visible = visible_datasets(user)
    covered_ids = set()
    if kept_features:
        covered_ids = set(
            valid_coverage("replica")
            .filter(geom_id__in=kept_features)
            .values_list("dataset_id", flat=True)
            .distinct()
        )

    for spec in req_data.get("dataset_specs") or []:
        name = (spec.get("datasetName") or "").strip()
        if not name:
            continue
        dataset = visible.filter(name=name).first()
        if dataset is None:
            dropped_datasets.append({"name": name, "title": spec.get("name") or name, "reason": "unavailable"})
            continue
        title = dataset.title or dataset.name
        if not dataset.is_global and dataset.id not in covered_ids:
            dropped_datasets.append({"name": name, "title": title, "reason": "not_covered"})
            continue

        kwargs = spec.get("kwargs") or None
        item = {
            "customName": (spec.get("name") or title) if kwargs else title,
            "datasetName": dataset.name,
            "datasetTitle": title,
            "datasetType": dataset.type,
            "processingClass": dataset.processing_class,
        }

        if kwargs:
            item["kwargs"] = kwargs
            item["filterSelections"] = _filter_selections(kwargs)
            datasets.append(item)
            continue

        # Rasters: keep the measures and periods that still exist
        extract_types = spec.get("extractTypes") or []
        resources = spec.get("resources") or []
        labels = dict(zip(resources, spec.get("resourceLabels") or resources))
        known_types = set(
            visible_processing_options_for_dataset(user, dataset)
            .filter(short_name__in=extract_types)
            .values_list("short_name", flat=True)
        )
        known_resources = {
            r.name: r
            for r in DatasetResource.objects.filter(dataset=dataset, name__in=resources)
        }
        kept_types = [t for t in extract_types if t in known_types]
        kept_resources = [r for r in resources if r in known_resources]
        if not kept_types or not kept_resources:
            dropped_datasets.append({"name": name, "title": title, "reason": "options_removed"})
            continue
        gone_types = [t for t in extract_types if t not in known_types]
        gone_resources = [labels.get(r, r) for r in resources if r not in known_resources]
        if gone_types or gone_resources:
            dropped_options.append(
                {"name": name, "title": title, "measures": gone_types, "periods": gone_resources}
            )
        item["extractTypes"] = kept_types
        item["resources"] = kept_resources
        item["resourceLabels"] = [
            labels.get(r) or known_resources[r].label or r for r in kept_resources
        ]
        datasets.append(item)

    return {
        "recipe": {
            "v": RECIPE_VERSION,
            "boundaries": {"fcIds": [fc.id for fc in fcs], "featureIds": feature_ids},
            "datasets": datasets,
        },
        "boundary_sets": [_fc_ref(fc) for fc in fcs],
        "dropped": {
            "features": dropped_features,
            "datasets": dropped_datasets,
            "options": dropped_options,
        },
    }
