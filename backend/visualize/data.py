"""
Visualization data builder.

Constructs per-request and per-explore DATA payloads consumed by the
frontend viz routes. Reads exclusively from the database so renderer
improvements apply to all past requests without re-running anything.
"""

from __future__ import annotations

import json

from django.contrib.gis.db.models import Extent

from features.models import Feature, FeatMap
from analytics.models import ExtractData, ExtractTask, ProcessingOption


def _fmt_kwargs(kwargs: dict) -> str:
    parts = []
    for key, val in kwargs.items():
        if isinstance(val, dict):
            if val.get("type") == "range":
                parts.append(f"{key}: {val.get('start')}–{val.get('end')}")
            elif val.get("type") == "categorical" and isinstance(val.get("selected"), list):
                parts.append(f"{key}: {', '.join(str(s) for s in val['selected'])}")
            else:
                parts.append(f"{key}: {json.dumps(val)}")
        else:
            parts.append(f"{key}: {val}")
    return "; ".join(parts)


def build_request_data(request) -> dict:
    """Build the visualization payload for a single Request.

    The returned dict matches the existing baked-HTML DATA shape so the
    renderer port is a straight 1:1 mapping. Tile base URL and Protomaps
    key are intentionally omitted — the frontend reads those from /api/config/.
    """
    # ── 1. Features touched by the request (one row per FeatMap) ─────────────
    feat_rows = (
        FeatMap.objects
        .filter(extracttask__requestmap__request=request)
        .select_related("fc")
        .values("geom_id", "name", "attr", "fc__name")
        .distinct()
    )

    features: dict[str, dict] = {}
    fc_names_set: set[str] = set()
    for fr in feat_rows:
        fc_name = fr["fc__name"]
        fc_names_set.add(fc_name)
        record: dict = {
            "name": fr["name"] or f"Feature {fr['geom_id']}",
            "fc": fc_name,
        }
        if fr["attr"]:
            for k, v in fr["attr"].items():
                record[f"boundary.{k}"] = v
        features[str(fr["geom_id"])] = record

    # ── 2. Extract data values + the metadata needed for column names ────────
    data_rows = (
        ExtractData.objects
        .filter(extract_task__requestmap__request=request)
        .values(
            "extract_task__fm__geom_id",
            "extract_task__resource__name",
            "extract_task__resource__label",
            "extract_task__resource__dataset__short_name",
            "extract_task__resource__dataset__title",
            "extract_task__resource__dataset__name",
            "extract_task__po__dataset_id",
            "extract_task__po__short_name",
            "extract_task__kwargs",
            "name",
            "data_column",
            "int_value", "float_value", "str_value",
        )
    )

    data_cols_set: set[str] = set()
    po_keys_per_col: dict[str, tuple[int, str]] = {}
    col_dataset_titles: dict[str, str] = {}
    col_temporal: dict[str, str] = {}
    col_kwargs: dict[str, dict] = {}

    for dr in data_rows:
        col = f"{dr['extract_task__resource__name']}.{dr['name']}"
        data_cols_set.add(col)
        po_keys_per_col[col] = (
            dr["extract_task__po__dataset_id"],
            dr["extract_task__po__short_name"],
        )
        if col not in col_dataset_titles:
            col_dataset_titles[col] = (
                dr["extract_task__resource__dataset__short_name"]
                or dr["extract_task__resource__dataset__title"]
                or dr["extract_task__resource__dataset__name"]
                or ""
            )
        if col not in col_temporal and dr["extract_task__resource__label"]:
            col_temporal[col] = dr["extract_task__resource__label"]
        if col not in col_kwargs and dr["extract_task__kwargs"]:
            col_kwargs[col] = dr["extract_task__kwargs"]

        geom_id = dr["extract_task__fm__geom_id"]
        record = features.get(str(geom_id))
        if record is None:
            continue  # data row points to a feature not in feat_map for this request

        dtype = dr["data_column"]
        if dtype == "int":
            value = dr["int_value"]
            value = int(value) if value is not None else None
        elif dtype == "float":
            value = dr["float_value"]
            value = float(value) if value is not None else None
        else:
            value = dr["str_value"]
        record[col] = value

    data_cols = sorted(data_cols_set)
    fc_names = sorted(fc_names_set)

    # ── 3. Column groups (resource name → list of columns) ───────────────────
    col_groups: dict[str, list[str]] = {}
    for col in data_cols:
        group = col.split(".", 1)[0]
        col_groups.setdefault(group, []).append(col)

    # ── 4. Column descriptions (ProcessingOption.description = units string) ─
    col_descriptions: dict[str, str] = {}
    if po_keys_per_col:
        ds_ids = {k[0] for k in po_keys_per_col.values() if k[0] is not None}
        short_names = {k[1] for k in po_keys_per_col.values() if k[1] is not None}
        if ds_ids and short_names:
            po_descriptions = {
                (po.dataset_id, po.short_name): po.description
                for po in ProcessingOption.objects.filter(
                    dataset_id__in=ds_ids,
                    short_name__in=short_names,
                )
                if po.description
            }
            for col, key in po_keys_per_col.items():
                desc = po_descriptions.get(key)
                if desc:
                    col_descriptions[col] = desc

    col_filter_desc: dict[str, str] = {
        col: _fmt_kwargs(kw) for col, kw in col_kwargs.items()
    }

    # ── 5. Bounding box from Feature geometries ──────────────────────────────
    bbox = None
    geom_ids = [int(k) for k in features.keys()]
    if geom_ids:
        extent = Feature.objects.filter(id__in=geom_ids).aggregate(
            extent=Extent("shape")
        )["extent"]
        if extent:
            bbox = list(extent)

    req_data = request.data or {}
    return {
        "request_id": str(request.id),
        "request_name": request.custom_name or str(request.id)[:8],
        "selection_label": req_data.get("selection_label") or "",
        "request_status": request.status,
        "fc_names": fc_names,
        "columns": data_cols,
        "col_groups": col_groups,
        "col_descriptions": col_descriptions,
        "col_filter_desc": col_filter_desc,
        "col_dataset_titles": col_dataset_titles,
        "col_temporal": col_temporal,
        "features": features,
        "bbox": bbox,
    }


def build_explore_data(fc_ids: list[int], po_ids: list[int]) -> dict:
    """Build the visualization payload for the explore page.

    Filters by FC and ProcessingOption IDs directly rather than through a
    request. Returns the same shape as build_request_data minus request-
    specific fields, so the frontend renderer works unchanged.
    """
    feat_rows = (
        FeatMap.objects
        .filter(fc_id__in=fc_ids)
        .select_related("fc")
        .values("geom_id", "name", "attr", "fc__name")
        .distinct()
    )

    features: dict[str, dict] = {}
    fc_names_set: set[str] = set()
    for fr in feat_rows:
        fc_name = fr["fc__name"]
        fc_names_set.add(fc_name)
        record: dict = {
            "name": fr["name"] or f"Feature {fr['geom_id']}",
            "fc": fc_name,
        }
        if fr["attr"]:
            for k, v in fr["attr"].items():
                record[f"boundary.{k}"] = v
        features[str(fr["geom_id"])] = record

    data_rows = (
        ExtractData.objects
        .filter(
            extract_task__fm__fc_id__in=fc_ids,
            extract_task__po_id__in=po_ids,
        )
        .values(
            "extract_task__fm__geom_id",
            "extract_task__resource__name",
            "extract_task__resource__label",
            "extract_task__resource__dataset__short_name",
            "extract_task__resource__dataset__title",
            "extract_task__resource__dataset__name",
            "extract_task__po__dataset_id",
            "extract_task__po__short_name",
            "extract_task__kwargs",
            "name",
            "data_column",
            "int_value", "float_value", "str_value",
        )
    )

    data_cols_set: set[str] = set()
    po_keys_per_col: dict[str, tuple[int, str]] = {}
    col_dataset_titles: dict[str, str] = {}
    col_temporal: dict[str, str] = {}
    col_kwargs: dict[str, dict] = {}

    for dr in data_rows:
        col = f"{dr['extract_task__resource__name']}.{dr['name']}"
        data_cols_set.add(col)
        po_keys_per_col[col] = (
            dr["extract_task__po__dataset_id"],
            dr["extract_task__po__short_name"],
        )
        if col not in col_dataset_titles:
            col_dataset_titles[col] = (
                dr["extract_task__resource__dataset__short_name"]
                or dr["extract_task__resource__dataset__title"]
                or dr["extract_task__resource__dataset__name"]
                or ""
            )
        if col not in col_temporal and dr["extract_task__resource__label"]:
            col_temporal[col] = dr["extract_task__resource__label"]
        if col not in col_kwargs and dr["extract_task__kwargs"]:
            col_kwargs[col] = dr["extract_task__kwargs"]
        geom_id = dr["extract_task__fm__geom_id"]
        record = features.get(str(geom_id))
        if record is None:
            continue

        dtype = dr["data_column"]
        if dtype == "int":
            value = dr["int_value"]
            value = int(value) if value is not None else None
        elif dtype == "float":
            value = dr["float_value"]
            value = float(value) if value is not None else None
        else:
            value = dr["str_value"]
        record[col] = value

    data_cols = sorted(data_cols_set)
    fc_names = sorted(fc_names_set)

    col_groups: dict[str, list[str]] = {}
    for col in data_cols:
        group = col.split(".", 1)[0]
        col_groups.setdefault(group, []).append(col)

    col_descriptions: dict[str, str] = {}
    if po_keys_per_col:
        ds_ids = {k[0] for k in po_keys_per_col.values() if k[0] is not None}
        short_names = {k[1] for k in po_keys_per_col.values() if k[1] is not None}
        if ds_ids and short_names:
            po_descriptions = {
                (po.dataset_id, po.short_name): po.description
                for po in ProcessingOption.objects.filter(
                    dataset_id__in=ds_ids,
                    short_name__in=short_names,
                )
                if po.description
            }
            for col, key in po_keys_per_col.items():
                desc = po_descriptions.get(key)
                if desc:
                    col_descriptions[col] = desc

    col_filter_desc: dict[str, str] = {
        col: _fmt_kwargs(kw) for col, kw in col_kwargs.items()
    }

    bbox = None
    geom_ids = [int(k) for k in features.keys()]
    if geom_ids:
        extent = Feature.objects.filter(id__in=geom_ids).aggregate(
            extent=Extent("shape")
        )["extent"]
        if extent:
            bbox = list(extent)

    return {
        "fc_names": fc_names,
        "columns": data_cols,
        "col_groups": col_groups,
        "col_descriptions": col_descriptions,
        "col_filter_desc": col_filter_desc,
        "col_dataset_titles": col_dataset_titles,
        "col_temporal": col_temporal,
        "features": features,
        "bbox": bbox,
    }


def build_explore_available(fc_ids: list[int]) -> list[dict]:
    """Return datasets + processing options that have completed extracts for
    the given FC IDs. Used by the explore page to populate the option picker."""
    rows = (
        ExtractTask.objects
        .filter(fm__fc_id__in=fc_ids, status=1)
        .values(
            "po_id",
            "po__short_name",
            "po__description",
            "resource__dataset_id",
            "resource__dataset__name",
            "resource__dataset__title",
        )
        .distinct()
        .order_by("resource__dataset__title", "po__short_name")
    )

    datasets: dict[int, dict] = {}
    for row in rows:
        ds_id = row["resource__dataset_id"]
        if ds_id not in datasets:
            datasets[ds_id] = {
                "dataset_id": ds_id,
                "dataset_name": row["resource__dataset__name"],
                "dataset_title": row["resource__dataset__title"] or row["resource__dataset__name"],
                "options": [],
            }
        datasets[ds_id]["options"].append({
            "po_id": row["po_id"],
            "short_name": row["po__short_name"],
            "description": row["po__description"] or "",
        })

    return list(datasets.values())
