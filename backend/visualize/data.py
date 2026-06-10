"""
Visualization data builder.

Constructs the per-request DATA payload consumed by the frontend viz route.
Reads exclusively from the database (extract_data + the request/task/feature
join chain) so improvements to the renderer apply to all past requests
without re-running anything.
"""

from __future__ import annotations

from django.contrib.gis.db.models import Extent

from features.models import Feature, FeatMap
from analytics.models import ExtractData, ProcessingOption


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
            "extract_task__resource__name",   # dr_name (column group)
            "extract_task__po__dataset_id",   # for description lookup
            "extract_task__po__short_name",   # for description lookup
            "name",                            # extract data column name
            "data_column",                     # 'int' | 'float' | 'str'
            "int_value", "float_value", "str_value",
        )
    )

    data_cols_set: set[str] = set()
    # column name → (dataset_id, po_short_name) for description lookup
    po_keys_per_col: dict[str, tuple[int, str]] = {}

    for dr in data_rows:
        col = f"{dr['extract_task__resource__name']}.{dr['name']}"
        data_cols_set.add(col)
        po_keys_per_col[col] = (
            dr["extract_task__po__dataset_id"],
            dr["extract_task__po__short_name"],
        )

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
        "fc_names": fc_names,
        "columns": data_cols,
        "col_groups": col_groups,
        "col_descriptions": col_descriptions,
        "features": features,
        "bbox": bbox,
    }
