"""The interactive map: an MCP App rendered inside the chat client.

The payload is built so the iframe can do most of its own work. Every selected
column's values are sent at once, so switching column, year, palette or
classification happens instantly in the browser with no server round trip --
only a change of dataset or extract type needs a new tool call. That is why
``values`` is keyed by column and geometry is sent once, separately, rather
than the obvious shape of one GeoJSON per column.

Caps are on features and on bytes. Over either, the geometry is dropped and
the summary stays: the numbers are still useful, and the "Open in GeoQuery"
link renders the full selection properly.
"""

from __future__ import annotations

import json

from django.conf import settings

from mcp_server.data import geometry
from mcp_server.data.palette import (
    CLASSIFICATIONS,
    DEFAULT_PALETTE,
    NO_DATA_COLOR,
    compute_breaks,
    compute_stats,
    resolve_palette,
)
from mcp_server.data.selection import (
    Selection,
    apply_formula,
    load_payload,
    resolve_selection,
    with_partial_flags,
)

MAP_APP_URI = "ui://geoquery/map.html"

# Protomaps' basemap tiles and the pinned ESM/CSS bundles the iframe loads.
# The chat host enforces these as a Content-Security-Policy, so anything the
# HTML fetches has to be listed here or it is silently blocked.
APP_RESOURCE_DOMAINS = [
    "https://unpkg.com",
    "https://protomaps.github.io",
]
APP_CONNECT_DOMAINS = [
    "https://api.protomaps.com",
    "https://unpkg.com",
    "https://protomaps.github.io",
]


def _numeric(values) -> list[float]:
    return [
        float(v)
        for v in values
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]


def _basemap() -> dict:
    """Protomaps style endpoints, matching MapFrame.svelte.

    The API key is embedded in the tile URL because that is how Protomaps
    authenticates, and the same key is already served to every browser by
    /api/config/ -- this exposes nothing new.
    """
    key = getattr(settings, "PROTOMAPS_API_KEY", "")
    return {
        "tiles": f"https://api.protomaps.com/tiles/v4/{{z}}/{{x}}/{{y}}.mvt?key={key}",
        "glyphs": "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf",
        "sprite": "https://protomaps.github.io/basemaps-assets/sprites/v4/light",
        "attribution": (
            '<a href="https://protomaps.com">Protomaps</a> © '
            '<a href="https://openstreetmap.org">OpenStreetMap</a>'
        ),
    }


def build_map_payload(
    user,
    *,
    boundaries=None,
    dataset=None,
    extract_type=None,
    years=None,
    resources=None,
    request_id=None,
    column=None,
    formula=None,
    palette=DEFAULT_PALETTE,
    classification="quantile",
    classes=5,
    include_geometry=True,
) -> dict:
    from mcp_server.tools.explore import attribution_for_selection, viz_url

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

    features = payload.get("features") or {}
    partial = with_partial_flags(payload)
    all_columns = list(payload.get("columns") or [])

    active = formula_column or column or (all_columns[0] if all_columns else None)
    if active and active not in all_columns:
        from mcp_server.data.selection import SelectionError

        raise SelectionError(
            f"No such column '{active}'. Available: "
            + (", ".join(all_columns) or "(none)")
        )

    # Only numeric columns can be a choropleth; a categorical column would
    # produce meaningless breaks. They stay out of the switcher entirely
    # rather than appearing and then failing to render.
    mappable = [c for c in all_columns if _numeric(f.get(c) for f in features.values())]
    if active and active not in mappable and mappable:
        active = mappable[0]

    values = {
        col: {
            geom_id: record.get(col)
            for geom_id, record in features.items()
            if isinstance(record.get(col), (int, float))
            and not isinstance(record.get(col), bool)
        }
        for col in mappable
    }

    classification = classification if classification in CLASSIFICATIONS else "quantile"
    classes = max(2, min(int(classes), 9))
    resolved_palette = resolve_palette(palette)

    active_values = _numeric(values.get(active, {}).values()) if active else []
    breaks = compute_breaks(active_values, classification, classes) if active_values else []

    geom_ids = [int(k) for k in features]
    bbox = payload.get("bbox") or geometry.bbox_for(geom_ids)
    geojson, truncated = _geometry_payload(
        selection, features, geom_ids, bbox, include_geometry
    )

    return {
        "source": selection.source,
        "title": _title(selection, payload),
        "viz_url": viz_url(
            selection,
            col=active,
            palette=resolved_palette["name"],
            scheme=classification,
            formula=formula,
        ),
        "columns": [
            {
                "name": col,
                "label": col.split(".", 1)[-1].replace("_", " "),
                "dataset_title": (payload.get("col_dataset_titles") or {}).get(col),
                "temporal": (payload.get("col_temporal") or {}).get(col),
                "partial": partial.get(col, False),
            }
            for col in mappable
        ],
        "column": active,
        "palette": resolved_palette,
        "classification": classification,
        "classes": classes,
        "breaks": breaks,
        "stats": compute_stats(active_values),
        "bbox": bbox,
        "no_data_color": NO_DATA_COLOR,
        "basemap": _basemap(),
        "values": values,
        "geojson": geojson,
        "feature_count": len(geom_ids),
        "truncated": truncated,
        "attribution": attribution_for_selection(selection),
    }


def _geometry_payload(
    selection: Selection, features: dict, geom_ids: list[int], bbox, include_geometry: bool
):
    """Geometry for the iframe, or ``None`` when it would be too large.

    Properties carry only ``name``: values travel separately in ``values`` so
    that switching column does not require re-sending every polygon.
    """
    if not include_geometry or not geom_ids:
        return None, False
    if len(geom_ids) > settings.MCP_MAP_MAX_FEATURES:
        return None, True

    geometries = geometry.geometries_for(selection.fc_ids, geom_ids, bbox)
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": geom_id,
                "geometry": geom,
                "properties": {"name": (features.get(str(geom_id)) or {}).get("name")},
            }
            for geom_id, geom in geometries.items()
        ],
    }
    # Byte cap as well as feature cap: a few thousand highly detailed
    # coastlines can blow past the size limit long before the feature count
    # does, and the host has to hold the whole payload in memory.
    if len(json.dumps(collection)) > settings.MCP_MAP_MAX_BYTES:
        return None, True
    return collection, False


def _title(selection: Selection, payload: dict) -> str:
    if selection.request_id:
        return payload.get("request_name") or f"Export {selection.request_id[:8]}"
    datasets = ", ".join(d.title or d.name for d in selection.datasets)
    places = ", ".join(selection.fc_names)
    return f"{datasets} — {places}" if datasets else places
