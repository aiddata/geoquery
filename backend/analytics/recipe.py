"""A past request as a request recipe (GEO-126): what "Use as template" loads.

The recipe has the frontend's shape (frontend/src/lib/recipe.ts):
``{"v": 1, "boundaries": {"fcIds", "featureIds"}, "datasets": [cart items]}``.
It is checked against the catalog as the viewer sees it now. Whatever no
longer applies (a dataset that's gone or doesn't cover these boundaries, a
period or measure that's been removed, features that weren't a whole boundary
set) is left out and listed, so the page can say what was dropped.
"""

from __future__ import annotations

import hashlib
import json
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


def _features_of(fcs) -> list[int]:
    return list(
        FeatMap.objects.filter(fc_id__in=[fc.id for fc in fcs]).values_list("geom_id", flat=True)
    )


def _check_datasets(user, specs: list[dict], kept_features: list[int]):
    """Dataset specs (as submitted, or a recipe's cart items mapped to that
    shape) as cart items, keeping what still applies: (datasets, dropped
    datasets, dropped options)."""
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

    for spec in specs:
        name = (spec.get("datasetName") or "").strip()
        if not name:
            continue
        dataset = visible.filter(name=name).first()
        if dataset is None:
            title = spec.get("datasetTitle") or spec.get("name") or name
            dropped_datasets.append({"name": name, "title": title, "reason": "unavailable"})
            continue
        title = dataset.title or dataset.name
        if not dataset.is_global and dataset.id not in covered_ids:
            dropped_datasets.append({"name": name, "title": title, "reason": "not_covered"})
            continue

        kwargs = spec.get("kwargs") or None
        item = {
            # Feature datasets: the version's name (its column prefix). Rasters:
            # a name given on Review, kept in a shared recipe.
            "customName": spec.get("name") or spec.get("customName") or title,
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
        # No periods chosen means the whole dataset: rasters with no time
        # periods ("Temporally Invariant") are requested that way. Only a
        # choice whose periods have all gone drops the dataset.
        if not kept_types or (resources and not kept_resources):
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

    return datasets, dropped_datasets, dropped_options


def _result(fc_ids, fcs, feature_ids, datasets, dropped_features, dropped_datasets, dropped_options):
    return {
        "recipe": {
            "v": RECIPE_VERSION,
            "boundaries": {"fcIds": fc_ids, "featureIds": feature_ids},
            "datasets": datasets,
        },
        "boundary_sets": [_fc_ref(fc) for fc in fcs],
        "dropped": {
            "features": dropped_features,
            "datasets": dropped_datasets,
            "options": dropped_options,
        },
    }


def request_recipe(user, req) -> dict:
    """The recipe for a past (standard-boundary) request, plus the boundary
    sets it names and what was dropped from it."""
    req_data = req.data or {}
    fcs, feature_ids, dropped_features = _boundaries(user, req_data)
    # Coverage is checked on the features the recipe keeps
    kept_features = feature_ids or _features_of(fcs)
    datasets, dropped_datasets, dropped_options = _check_datasets(
        user, req_data.get("dataset_specs") or [], kept_features
    )
    return _result(
        [fc.id for fc in fcs], fcs, feature_ids, datasets,
        dropped_features, dropped_datasets, dropped_options,
    )


def check_recipe(user, recipe: dict) -> dict:
    """A stored recipe (a share link's) checked against the catalog as the
    viewer sees it now, in the same shape as request_recipe. Boundary sets
    that are gone are left out of boundary_sets, and the frontend's loader
    reports them; features outside a single set are dropped."""
    boundaries = recipe.get("boundaries") or {}
    fc_ids = [i for i in boundaries.get("fcIds") or [] if type(i) is int]
    found = {fc.id: fc for fc in visible_feature_collections(user).filter(id__in=fc_ids)}
    fcs = [found[i] for i in fc_ids if i in found]

    feature_ids: list[int] = []
    dropped_features = 0
    wanted = [i for i in boundaries.get("featureIds") or [] if type(i) is int]
    if wanted and len(fc_ids) == 1:
        if fcs:
            in_set = set(
                FeatMap.objects.filter(fc=fcs[0], geom_id__in=wanted).values_list("geom_id", flat=True)
            )
            feature_ids = [i for i in wanted if i in in_set]
        dropped_features = len(wanted) - len(feature_ids)

    kept_features = feature_ids or _features_of(fcs)
    specs = [
        {**item, "name": item.get("customName") if item.get("kwargs") else None}
        for item in recipe.get("datasets") or []
        if isinstance(item, dict)
    ]
    datasets, dropped_datasets, dropped_options = _check_datasets(user, specs, kept_features)
    return _result(
        fc_ids, fcs, feature_ids, datasets,
        dropped_features, dropped_datasets, dropped_options,
    )


# ── Share links ──────────────────────────────────────────────────────────────

MAX_RECIPE_BYTES = 200_000
_ITEM_KEYS = (
    "customName", "datasetName", "datasetTitle", "datasetType", "processingClass",
    "extractTypes", "resources", "resourceLabels", "filterSelections", "kwargs",
)
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


class InvalidRecipe(ValueError):
    pass


def _ids(value, what) -> list[int]:
    if not isinstance(value, list) or not all(type(i) is int and i > 0 for i in value):
        raise InvalidRecipe(f"{what} must be a list of ids")
    return value


def normalize_recipe(value) -> dict:
    """A recipe from a client, reduced to the fields a recipe has: what a
    share link stores. Raises InvalidRecipe for anything that isn't one."""
    if not isinstance(value, dict) or value.get("v") != RECIPE_VERSION:
        raise InvalidRecipe("not a recipe this version understands")
    boundaries = value.get("boundaries")
    if not isinstance(boundaries, dict):
        raise InvalidRecipe("boundaries are missing")
    fc_ids = _ids(boundaries.get("fcIds"), "boundaries.fcIds")
    if not fc_ids:
        raise InvalidRecipe("a recipe needs at least one boundary set")
    feature_ids = _ids(boundaries.get("featureIds", []), "boundaries.featureIds")
    datasets = value.get("datasets")
    if not isinstance(datasets, list):
        raise InvalidRecipe("datasets must be a list")
    items = []
    for item in datasets:
        if not isinstance(item, dict) or not isinstance(item.get("datasetName"), str):
            raise InvalidRecipe("each dataset needs a datasetName")
        items.append({k: item[k] for k in _ITEM_KEYS if k in item})
    recipe = {
        "v": RECIPE_VERSION,
        "boundaries": {"fcIds": fc_ids, "featureIds": feature_ids if len(fc_ids) == 1 else []},
        "datasets": items,
    }
    if len(canonical_json(recipe)) > MAX_RECIPE_BYTES:
        raise InvalidRecipe("this request is too large to share")
    return recipe


def canonical_json(recipe: dict) -> bytes:
    return json.dumps(recipe, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def share_id(recipe: dict, length: int = 10) -> str:
    """A short id derived from the recipe: the same recipe, the same link."""
    n = int.from_bytes(hashlib.sha256(canonical_json(recipe)).digest(), "big")
    chars = []
    for _ in range(length):
        n, r = divmod(n, len(_ALPHABET))
        chars.append(_ALPHABET[r])
    return "".join(chars)
