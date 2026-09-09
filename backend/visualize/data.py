"""
Visualization data builder.

Constructs per-request and per-explore DATA payloads consumed by the
frontend viz routes. Reads exclusively from the database so renderer
improvements apply to all past requests without re-running anything.
"""

from __future__ import annotations

import json

from django.contrib.gis.db.models import Extent
from django.db import connection

from features.models import Feature, FeatMap
from analytics.models import ExtractTask, ProcessingOption
from datasets.models import Dataset


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


def _dictfetchall(cursor) -> list[dict]:
    """Return all rows from a cursor as a list of dicts keyed by column name.

    Standard Django raw-SQL recipe -- lets the aggregation loops below index
    rows by name exactly like the ORM's .values(...) querysets they replace.
    """
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _load_jsonb(value):
    """Decode a jsonb column value fetched via a raw cursor.

    Django's postgresql backend registers psycopg2's jsonb loader with
    ``loads=lambda x: x`` (see django/db/backends/postgresql/base.py) so that
    ORM JSONField reads aren't double-decoded through Django's own decoder --
    but that means jsonb values fetched through a raw cursor (bypassing
    JSONField entirely, as here) come back as the raw JSON text, not a dict.
    """
    return json.loads(value) if isinstance(value, str) else value


# Reconstructs the pre-redesign one-row-per-(task, resource, name) shape from
# ExtractTask.resource_ids and ExtractData's float_values/int_values/
# str_values arrays (see analytics.models.ExtractTask/ExtractData
# docstrings for the position-alignment invariant this depends on).
#
# unnest(et.resource_ids, ed.float_values, ed.int_values, ed.str_values)
# WITH ORDINALITY walks all four arrays in lockstep by position: position i
# of resource_ids pairs with position i of each value array, one output row
# per position. Only one of the three value arrays is ever populated per
# ExtractData row (matching ed.data_column); the other two are genuinely
# NULL, not empty arrays. Per Postgres semantics, a NULL array argument to a
# multi-array unnest() is treated as an empty array, so its column comes
# back NULL for every row the *other*, populated arrays generate -- which is
# exactly what lets the Python loop below keep branching on data_column to
# pick one of int_value/float_value/str_value, unchanged from how it read
# the old scalar columns of the same names.
#
# Joins wherever extract_tasks/extract_data appear include dataset_id
# alongside the id column: both tables are LIST partitioned on dataset_id
# (see migration 0021_partition_extract_tasks_and_data), and including the
# partition key in the join condition lets Postgres do a partition-wise join
# instead of scanning every partition. Not required for correctness (a
# single IDENTITY sequence backs the whole partitioned table, so ids are
# already globally unique) -- just free performance.
_REQUEST_EXTRACT_DATA_SQL = """
    SELECT
        fm.geom_id AS geom_id,
        dr.name AS resource_name,
        dr.label AS resource_label,
        d.short_name AS dataset_short_name,
        d.title AS dataset_title,
        d.name AS dataset_name,
        po.dataset_id AS po_dataset_id,
        po.short_name AS po_short_name,
        et.kwargs AS task_kwargs,
        ed.name AS name,
        ed.data_column AS data_column,
        u.int_value AS int_value,
        u.float_value AS float_value,
        u.str_value AS str_value
    FROM extract_data ed
    INNER JOIN extract_tasks et
        ON et.dataset_id = ed.dataset_id AND et.id = ed.extract_task_id
    INNER JOIN request_map rm
        ON rm.dataset_id = et.dataset_id AND rm.task_id = et.id
    INNER JOIN feat_map fm ON fm.id = et.fm_id
    INNER JOIN processing_options po ON po.id = et.po_id
    CROSS JOIN LATERAL unnest(et.resource_ids, ed.float_values, ed.int_values, ed.str_values)
        WITH ORDINALITY AS u(resource_id, float_value, int_value, str_value, ord)
    INNER JOIN dataset_resources dr ON dr.id = u.resource_id
    INNER JOIN datasets d ON d.id = dr.dataset_id
    WHERE rm.req_id = %s
"""

# Same shape as _REQUEST_EXTRACT_DATA_SQL (see its comment for the unnest and
# partition-wise-join rationale, both identical here) but filtered directly
# by fc/po id, mirroring how build_explore_data's old ORM query filtered on
# extract_task__fm__fc_id__in / extract_task__po_id__in instead of going
# through request_map.
_EXPLORE_EXTRACT_DATA_SQL = """
    SELECT
        fm.geom_id AS geom_id,
        dr.name AS resource_name,
        dr.label AS resource_label,
        d.short_name AS dataset_short_name,
        d.title AS dataset_title,
        d.name AS dataset_name,
        po.dataset_id AS po_dataset_id,
        po.short_name AS po_short_name,
        et.kwargs AS task_kwargs,
        ed.name AS name,
        ed.data_column AS data_column,
        u.int_value AS int_value,
        u.float_value AS float_value,
        u.str_value AS str_value
    FROM extract_data ed
    INNER JOIN extract_tasks et
        ON et.dataset_id = ed.dataset_id AND et.id = ed.extract_task_id
    INNER JOIN feat_map fm ON fm.id = et.fm_id
    INNER JOIN processing_options po ON po.id = et.po_id
    CROSS JOIN LATERAL unnest(et.resource_ids, ed.float_values, ed.int_values, ed.str_values)
        WITH ORDINALITY AS u(resource_id, float_value, int_value, str_value, ord)
    INNER JOIN dataset_resources dr ON dr.id = u.resource_id
    INNER JOIN datasets d ON d.id = dr.dataset_id
    WHERE fm.fc_id = ANY(%s) AND et.po_id = ANY(%s)
"""


def _aggregate_data_rows(data_rows: list[dict], features: dict[str, dict]):
    """Shared aggregation for build_request_data/build_explore_data.

    Walks the flattened (one-row-per-resource) rows from either extract-data
    SQL constant above, filling `features` in place and returning the column
    bookkeeping both callers assemble the rest of the payload from.
    """
    data_cols_set: set[str] = set()
    po_keys_per_col: dict[str, tuple[int, str]] = {}
    col_dataset_titles: dict[str, str] = {}
    col_temporal: dict[str, str] = {}
    col_kwargs: dict[str, dict] = {}

    for dr in data_rows:
        col = f"{dr['resource_name']}.{dr['name']}"
        data_cols_set.add(col)
        po_keys_per_col[col] = (dr["po_dataset_id"], dr["po_short_name"])
        if col not in col_dataset_titles:
            col_dataset_titles[col] = (
                dr["dataset_short_name"]
                or dr["dataset_title"]
                or dr["dataset_name"]
                or ""
            )
        if col not in col_temporal and dr["resource_label"]:
            col_temporal[col] = dr["resource_label"]
        if col not in col_kwargs and dr["task_kwargs"]:
            col_kwargs[col] = _load_jsonb(dr["task_kwargs"])

        geom_id = dr["geom_id"]
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

    return data_cols_set, po_keys_per_col, col_dataset_titles, col_temporal, col_kwargs


def _col_descriptions_for(po_keys_per_col: dict[str, tuple[int, str]]) -> dict[str, str]:
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
    return col_descriptions


def _feature_rows(**filter_kwargs) -> tuple[dict[str, dict], set[str]]:
    feat_rows = (
        FeatMap.objects
        .filter(**filter_kwargs)
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
    return features, fc_names_set


def _bbox_for(features: dict[str, dict]):
    geom_ids = [int(k) for k in features.keys()]
    if not geom_ids:
        return None
    extent = Feature.objects.filter(id__in=geom_ids).aggregate(extent=Extent("shape"))["extent"]
    return list(extent) if extent else None


def build_request_data(request) -> dict:
    """Build the visualization payload for a single Request.

    The returned dict matches the existing baked-HTML DATA shape so the
    renderer port is a straight 1:1 mapping. Tile base URL and Protomaps
    key are intentionally omitted — the frontend reads those from /api/config/.
    """
    # ── 1. Features touched by the request (one row per FeatMap) ─────────────
    features, fc_names_set = _feature_rows(extracttask__requestmap__request=request)

    # ── 2. Extract data values + the metadata needed for column names ────────
    with connection.cursor() as cursor:
        cursor.execute(_REQUEST_EXTRACT_DATA_SQL, [str(request.id)])
        data_rows = _dictfetchall(cursor)

    data_cols_set, po_keys_per_col, col_dataset_titles, col_temporal, col_kwargs = (
        _aggregate_data_rows(data_rows, features)
    )

    data_cols = sorted(data_cols_set)
    fc_names = sorted(fc_names_set)

    # ── 3. Column groups (resource name → list of columns) ───────────────────
    col_groups: dict[str, list[str]] = {}
    for col in data_cols:
        group = col.split(".", 1)[0]
        col_groups.setdefault(group, []).append(col)

    # ── 4. Column descriptions (ProcessingOption.description = units string) ─
    col_descriptions = _col_descriptions_for(po_keys_per_col)

    col_filter_desc: dict[str, str] = {
        col: _fmt_kwargs(kw) for col, kw in col_kwargs.items()
    }

    # ── 5. Bounding box from Feature geometries ──────────────────────────────
    bbox = _bbox_for(features)

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
    features, fc_names_set = _feature_rows(fc_id__in=fc_ids)

    with connection.cursor() as cursor:
        cursor.execute(_EXPLORE_EXTRACT_DATA_SQL, [fc_ids, po_ids])
        data_rows = _dictfetchall(cursor)

    data_cols_set, po_keys_per_col, col_dataset_titles, col_temporal, col_kwargs = (
        _aggregate_data_rows(data_rows, features)
    )

    data_cols = sorted(data_cols_set)
    fc_names = sorted(fc_names_set)

    col_groups: dict[str, list[str]] = {}
    for col in data_cols:
        group = col.split(".", 1)[0]
        col_groups.setdefault(group, []).append(col)

    col_descriptions = _col_descriptions_for(po_keys_per_col)

    col_filter_desc: dict[str, str] = {
        col: _fmt_kwargs(kw) for col, kw in col_kwargs.items()
    }

    bbox = _bbox_for(features)

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


def build_explore_available(fc_ids: list[int], po_ids: list[int]) -> list[dict]:
    """Return datasets + processing options that have completed extracts for
    the given FC IDs. Used by the explore page to populate the option picker.

    The caller is responsible for having narrowed both id lists to what the
    requesting user may see -- see catalog.access and ExploreAvailableView.

    Unlike build_request_data/build_explore_data, this aggregates at the
    (dataset, po) level only -- it never needs to know which individual
    resources a grouped task covers -- so there's nothing to unnest.
    ExtractTask.dataset_id is a plain column directly on the table, so the
    dataset grouping is a direct .values() on ExtractTask; dataset
    name/title come from a separate lookup dict rather than an ORM
    traversal, the same pattern _col_descriptions_for/po_descriptions above
    uses for ProcessingOption.
    """
    rows = list(
        ExtractTask.objects
        .filter(fm__fc_id__in=fc_ids, po_id__in=po_ids, status=1)
        .values("dataset_id", "po_id", "po__short_name", "po__description")
        .distinct()
    )

    dataset_ids = {row["dataset_id"] for row in rows}
    dataset_lookup = {
        d["id"]: d
        for d in Dataset.objects.filter(id__in=dataset_ids).values("id", "name", "title")
    }

    def _sort_key(row):
        ds = dataset_lookup.get(row["dataset_id"], {})
        title = ds.get("title") or ds.get("name") or ""
        return (title, row["po__short_name"] or "")

    rows.sort(key=_sort_key)

    datasets: dict[int, dict] = {}
    for row in rows:
        ds_id = row["dataset_id"]
        if ds_id not in datasets:
            ds = dataset_lookup.get(ds_id, {})
            datasets[ds_id] = {
                "dataset_id": ds_id,
                "dataset_name": ds.get("name"),
                "dataset_title": ds.get("title") or ds.get("name"),
                "options": [],
            }
        datasets[ds_id]["options"].append({
            "po_id": row["po_id"],
            "short_name": row["po__short_name"],
            "description": row["po__description"] or "",
        })

    return list(datasets.values())
