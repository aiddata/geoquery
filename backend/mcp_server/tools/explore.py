"""Reading values: a table, or GeoJSON.

``get_data`` is the one tool that returns actual numbers, from either source
(live pre-processed extracts, or a finished export). Two shapes come out of it
because two very different things happen next: a table is for the model to
read and reason about, and GeoJSON is for a client that wants to draw its own
map -- ChatGPT and Claude both build perfectly good visualizations from it,
and unlike ``show_map`` it needs no app support.

Caps are deliberate and reported rather than silently applied. When a
selection is too big the right move is to narrow it or hand the user
``viz_url``, which opens the whole thing in GeoQuery's own map -- not to page
a million rows through a chat window.
"""

from __future__ import annotations

import json
from typing import Annotated
from urllib.parse import quote

from django.conf import settings
from pydantic import Field

from mcp_server.data import geometry
from mcp_server.data.attribution import attribution_for, attribution_for_request
from mcp_server.data.selection import (
    Selection,
    SelectionError,
    apply_formula,
    load_payload,
    resolve_selection,
    with_partial_flags,
)
from mcp_server.schemas import (
    BOUNDARIES_DESC,
    DATA_OUTPUT_SCHEMA,
    DATASET_DESC,
    EXTRACT_TYPE_DESC,
    FORMULA_DESC,
    Format,
    REQUEST_ID_DESC,
    RESOURCES_DESC,
    YEARS_DESC,
)

from .common import READ_ONLY, fmt_count, result, tool_body


def attribution_for_selection(selection: Selection) -> dict:
    if selection.request_id:
        from analytics.models import Request

        return attribution_for_request(Request.objects.get(id=selection.request_id))
    return attribution_for(selection.datasets, selection.feature_collections)


def viz_url(selection: Selection, **params) -> str | None:
    """Deep link into the web app showing exactly this selection.

    The escape hatch for everything the caps cut off: every truncated result
    carries one, so "too much data for chat" always has an answer better than
    "try a smaller query".
    """
    base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
    if not base:
        return None

    if selection.request_id:
        url = f"{base}/viz/{selection.request_id}"
    else:
        fc = ",".join(str(i) for i in selection.fc_ids)
        po = ",".join(str(i) for i in selection.po_ids)
        url = f"{base}/viz/explore?fc={fc}&po={po}"

    query = "&".join(
        f"{key}={quote(str(value))}" for key, value in params.items() if value
    )
    if not query:
        return url
    return f"{url}{'&' if '?' in url else '?'}{query}"


def _select_columns(payload: dict, columns: list[str] | None, limit: int) -> list[str]:
    """Which columns to return, and in which order.

    An explicit list is honoured exactly (so a follow-up call can ask for the
    two columns the model actually wants); otherwise the first `limit` in the
    payload's own sort order. Naming a column that is not there is an error
    rather than a silent omission -- a model that misspells a column should
    find out, not get a table that quietly lacks it.
    """
    available = list(payload.get("columns") or [])
    if columns:
        missing = [c for c in columns if c not in available]
        if missing:
            raise SelectionError(
                f"No such column(s): {', '.join(missing)}. Available: "
                + (", ".join(available) or "(none)")
            )
        return columns
    return available[:limit]


def _sorted_rows(features: dict, column: str | None, descending: bool) -> list[tuple]:
    """Feature items ordered by name, or by a column when asked.

    Nulls always sort last, in both directions: a "top 10" that is actually
    ten features with no data is the single most misleading thing this tool
    could return.
    """
    items = list(features.items())
    if column is None:
        return sorted(items, key=lambda kv: (kv[1].get("name") or "", kv[0]))

    def key(kv):
        value = kv[1].get(column)
        missing = value is None or isinstance(value, str)
        return (missing, -(value or 0) if descending and not missing else (value or 0))

    return sorted(items, key=key)


def _column_stats(features: dict, columns: list[str]) -> dict:
    from mcp_server.data.palette import compute_stats

    stats = {}
    for col in columns:
        values = [
            float(f[col])
            for f in features.values()
            if isinstance(f.get(col), (int, float)) and not isinstance(f.get(col), bool)
        ]
        computed = compute_stats(values)
        if computed:
            stats[col] = {k: round(v, 6) if isinstance(v, float) else v for k, v in computed.items()}
    return stats


def _column_meta(payload: dict, columns: list[str], partial: dict) -> list[dict]:
    return [
        {
            "name": col,
            "dataset_title": (payload.get("col_dataset_titles") or {}).get(col),
            "temporal": (payload.get("col_temporal") or {}).get(col),
            "description": (payload.get("col_descriptions") or {}).get(col),
            "filter_desc": (payload.get("col_filter_desc") or {}).get(col) or None,
            "partial": partial.get(col, False),
        }
        for col in columns
    ]


def _matches_search(record: dict, needle: str) -> bool:
    return needle in (record.get("name") or "").lower()


def _get_data(
    user,
    *,
    boundaries=None,
    dataset=None,
    extract_type=None,
    years=None,
    resources=None,
    request_id=None,
    columns=None,
    formula=None,
    format="table",
    offset=0,
    limit=100,
    sort_by=None,
    descending=False,
    search=None,
) -> dict:
    selection = resolve_selection(
        user,
        boundaries=boundaries,
        dataset=dataset,
        extract_type=extract_type,
        years=years,
        resources=resources,
        request_id=request_id,
    )
    payload = load_payload(selection)
    formula_column = apply_formula(payload, formula) if formula else None

    max_columns = settings.MCP_RESULTS_MAX_COLUMNS
    selected = _select_columns(payload, columns, max_columns)
    if formula_column and formula_column not in selected:
        # The caller asked for this column by writing the formula; it is never
        # the one dropped by the column cap.
        selected = [formula_column, *selected][:max_columns]

    partial = with_partial_flags(payload)
    features = payload.get("features") or {}
    if search:
        needle = search.lower()
        features = {k: v for k, v in features.items() if _matches_search(v, needle)}

    attribution = attribution_for_selection(selection)
    common = {
        "source": selection.source,
        "format": format,
        "fc_names": payload.get("fc_names") or selection.fc_names,
        "columns_omitted": max(0, len(payload.get("columns") or []) - len(selected)),
        "attribution": attribution,
    }

    if format == "geojson":
        result_payload = {
            **common,
            **_geojson(selection, payload, features, selected, partial, attribution),
        }
    else:
        result_payload = {
            **common,
            **_table(
                selection,
                payload,
                features,
                selected,
                partial,
                offset,
                limit,
                sort_by,
                descending,
                formula,
            ),
        }
    return _fit_model_payload(result_payload)


def _json_size(payload: dict) -> int:
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _fit_model_payload(payload: dict) -> dict:
    """Keep get_data within the model context cap and say exactly what was cut.

    Geometry is removed before values because the values are what a model can
    reason about. If the values alone exceed the cap, return the largest
    leading slice that fits and expose both total and returned counts.
    """
    cap = settings.MCP_MODEL_CONTENT_MAX_BYTES
    payload["content_truncated"] = False
    if payload["format"] == "table":
        payload["returned_rows"] = len(payload["rows"])
    else:
        payload["returned_features"] = len(payload["geojson"]["features"])
    if _json_size(payload) <= cap:
        return payload

    if payload["format"] == "geojson":
        collection = {**payload["geojson"]}
        collection["features"] = [
            {**feature, "geometry": None} for feature in collection["features"]
        ]
        payload["geojson"] = collection
        payload["geometry_omitted"] = True
        payload["truncated"] = True
        payload["content_truncated"] = True
        if _json_size(payload) <= cap:
            return payload
        items_key = "features"
        items = collection[items_key]
        count_key = "returned_features"
    else:
        items_key = "rows"
        items = payload[items_key]
        count_key = "returned_rows"
        payload["truncated"] = True
        payload["content_truncated"] = True

    low, high = 0, len(items)
    while low < high:
        midpoint = (low + high + 1) // 2
        candidate = {**payload, count_key: midpoint}
        if payload["format"] == "geojson":
            candidate["geojson"] = {**payload["geojson"], items_key: items[:midpoint]}
        else:
            candidate[items_key] = items[:midpoint]
        if _json_size(candidate) <= cap:
            low = midpoint
        else:
            high = midpoint - 1

    payload[count_key] = low
    if payload["format"] == "geojson":
        payload["geojson"] = {**payload["geojson"], items_key: items[:low]}
    else:
        payload[items_key] = items[:low]
    return payload


def _table(
    selection, payload, features, selected, partial,
    offset, limit, sort_by, descending, formula,
) -> dict:
    if sort_by and sort_by not in selected:
        raise SelectionError(
            f"Cannot sort by '{sort_by}': it is not one of the returned "
            f"columns ({', '.join(selected) or 'none'})."
        )

    max_rows = settings.MCP_RESULTS_MAX_ROWS
    limit = max(1, min(limit, max_rows))
    ordered = _sorted_rows(features, sort_by, descending)
    page = ordered[offset : offset + limit]

    return {
        "columns": _column_meta(payload, selected, partial),
        "column_stats": _column_stats(features, selected),
        "rows": [
            {
                "feature_id": int(geom_id),
                "name": record.get("name"),
                "fc": record.get("fc"),
                "values": {col: record.get(col) for col in selected},
            }
            for geom_id, record in page
        ],
        "offset": offset,
        "limit": limit,
        "total_rows": len(ordered),
        "truncated": offset + len(page) < len(ordered),
        "viz_url": viz_url(
            selection,
            col=selected[0] if selected else None,
            formula=formula,
        ),
    }


def _geojson(selection, payload, features, selected, partial, attribution) -> dict:
    """A GeoJSON FeatureCollection the client can render itself.

    Over the feature cap the geometry is dropped rather than the features:
    the values are what the model reasons about, and a caller that wanted a
    picture can follow ``viz_url``. Dropping geometry keeps the answer
    correct; dropping features would make it wrong.
    """
    geom_ids = [int(k) for k in features]
    over_cap = len(geom_ids) > settings.MCP_MAP_MAX_FEATURES

    # The payload already knows the extent, so pass it through rather than
    # making geometries_for re-aggregate it just to pick a simplification tier.
    geometries = (
        {}
        if over_cap
        else geometry.geometries_for(selection.fc_ids, geom_ids, payload.get("bbox"))
    )

    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": int(geom_id),
                "geometry": geometries.get(int(geom_id)),
                "properties": {
                    "name": record.get("name"),
                    "fc": record.get("fc"),
                    **{col: record.get(col) for col in selected},
                },
            }
            for geom_id, record in features.items()
        ],
        # Not part of the GeoJSON spec, which permits foreign members. Carried
        # inside the collection on purpose: a client that saves or forwards
        # the GeoJSON takes the attribution with it.
        "attribution": attribution,
    }

    return {
        "geojson": collection,
        "columns": _column_meta(payload, selected, partial),
        "column_stats": _column_stats(features, selected),
        "feature_count": len(geom_ids),
        "geometry_omitted": over_cap,
        "truncated": over_cap,
        "bbox": payload.get("bbox"),
        "viz_url": viz_url(selection, col=selected[0] if selected else None),
    }


def register(mcp, user_dep):
    @mcp.tool(annotations=READ_ONLY, output_schema=DATA_OUTPUT_SCHEMA)
    @tool_body
    def get_data(
        boundaries: Annotated[
            list[str] | None, Field(description=BOUNDARIES_DESC)
        ] = None,
        dataset: Annotated[str | None, Field(description=DATASET_DESC)] = None,
        extract_type: Annotated[
            str | None, Field(description=EXTRACT_TYPE_DESC)
        ] = None,
        years: Annotated[list[int] | None, Field(description=YEARS_DESC)] = None,
        resources: Annotated[
            list[str] | None, Field(description=RESOURCES_DESC)
        ] = None,
        request_id: Annotated[str | None, Field(description=REQUEST_ID_DESC)] = None,
        columns: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Exact column names to return. Omit to get the first "
                    "columns of the selection."
                )
            ),
        ] = None,
        formula: Annotated[str | None, Field(description=FORMULA_DESC)] = None,
        format: Annotated[
            Format,
            Field(
                description=(
                    "'table' for values to read; 'geojson' for boundary "
                    "geometry with the values attached, to draw your own map."
                )
            ),
        ] = "table",
        offset: Annotated[int, Field(description="Rows to skip.", ge=0)] = 0,
        limit: Annotated[int, Field(description="Rows to return.", ge=1)] = 100,
        sort_by: Annotated[
            str | None, Field(description="Column to sort by. Nulls always sort last.")
        ] = None,
        descending: Annotated[bool, Field(description="Sort high to low.")] = False,
        search: Annotated[
            str | None, Field(description="Only features whose name contains this.")
        ] = None,
        user=user_dep,
    ):
        """Read values for a selection, as a table or as GeoJSON.

        Two sources: `boundaries` + `dataset` reads pre-processed data live
        (fast, no waiting), or `request_id` reads a finished export.

        Use `format="geojson"` when you want to draw the map yourself; it
        returns boundary geometry with the values attached, and its own
        `attribution` member.

        Results are capped. If `truncated` is true, narrow the selection or
        give the user `viz_url`, which opens the whole thing in GeoQuery.
        Results include `attribution`; relay the sources, licenses and
        citations to the user.
        """
        payload = _get_data(
            user,
            boundaries=boundaries,
            dataset=dataset,
            extract_type=extract_type,
            years=years,
            resources=resources,
            request_id=request_id,
            columns=columns,
            formula=formula,
            format=format,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            descending=descending,
            search=search,
        )

        if format == "geojson":
            lines = [
                f"GeoJSON for {fmt_count(payload['feature_count'], 'feature')} "
                f"across {', '.join(payload['fc_names']) or 'no boundaries'}, "
                f"with {fmt_count(len(payload['columns']), 'column')}."
            ]
            if payload["geometry_omitted"]:
                lines.append(
                    f"Over the {settings.MCP_MAP_MAX_FEATURES:,}-feature limit, so "
                    "geometry was omitted and only values are included. Narrow "
                    f"the selection, or open {payload['viz_url']}."
                )
        else:
            lines = [
                f"{fmt_count(payload['total_rows'], 'feature')} "
                f"× {fmt_count(len(payload['columns']), 'column')}; showing rows "
                f"{payload['offset'] + 1}–{payload['offset'] + len(payload['rows'])}."
            ]
            if payload["truncated"]:
                lines.append(
                    f"More rows available — raise `offset`, or open {payload['viz_url']}."
                )
        partial = [c["name"] for c in payload["columns"] if c["partial"]]
        if partial:
            lines.append(
                "Partly processed (some features have no value): "
                + ", ".join(partial)
                + " — say so if you summarise these."
            )
        if payload["columns_omitted"]:
            lines.append(
                f"{payload['columns_omitted']} further column(s) not shown; name "
                "them in `columns` to see them."
            )
        if payload["content_truncated"]:
            returned = payload.get("returned_rows", payload.get("returned_features", 0))
            lines.append(
                f"The response-size limit retained {returned:,} records. Narrow "
                f"the selection or open {payload['viz_url']} for the full result."
            )
        return result(lines, payload)
