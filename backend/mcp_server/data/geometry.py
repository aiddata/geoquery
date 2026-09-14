"""Simplified geometry for GeoJSON and map payloads.

A chat client renders whatever JSON it is handed, so full-resolution
boundaries are not an option: one African ADM2 collection at full detail is
tens of megabytes, which no client will draw and most will refuse to hold.

These reads go against the pre-simplified tables the vector-tile endpoint
already maintains (``features.matviews``) rather than calling ``ST_Simplify``
per request: the work is already done, the tolerances are already tuned per
zoom tier, and the boundaries come out topologically consistent because
``ST_CoverageSimplify`` simplified each collection as a coverage.
"""

from __future__ import annotations

import json

from django.contrib.gis.db.models import Extent
from django.db import connection

from features.models import Feature

# The tile endpoint's z0-5 and z6-9 tiers (see features.matviews). The coarse
# tier is for a continent-or-larger view where the fine one would be wasted
# detail; the fine tier is the default because an MCP selection is usually one
# country or smaller.
_COARSE_TABLE = "features_simplified_z0_5"
_FINE_TABLE = "features_simplified_z6_9"

# Degrees of bbox span above which the coarse tier is used. Matches the zoom
# at which the tile endpoint switches: roughly, more than ~10 degrees on a
# side is a z<=5 view.
_COARSE_SPAN_DEGREES = 10.0

# Coordinate precision in the emitted GeoJSON. 4 decimal places is about 11 m
# at the equator -- finer than the simplification tolerance of either tier, so
# it costs no visible detail and roughly halves the payload.
_COORD_PRECISION = 4

_GEOJSON_SQL = """
    SELECT geom_id, ST_AsGeoJSON(ST_Transform(shape, 4326), %s)
    FROM {table}
    WHERE fc_id = ANY(%s) AND geom_id = ANY(%s)
"""


def bbox_for(geom_ids: list[int]) -> list[float] | None:
    """``[west, south, east, north]`` for a set of features, or ``None``."""
    if not geom_ids:
        return None
    extent = Feature.objects.filter(id__in=geom_ids).aggregate(
        extent=Extent("shape")
    )["extent"]
    return list(extent) if extent else None


def pick_table(bbox: list[float] | None) -> str:
    """Which simplified tier to read, from how much of the world is in view."""
    if bbox is None:
        return _FINE_TABLE
    west, south, east, north = bbox
    span = max(east - west, north - south)
    return _COARSE_TABLE if span > _COARSE_SPAN_DEGREES else _FINE_TABLE


def geometries_for(
    fc_ids: list[int], geom_ids: list[int], bbox: list[float] | None = None
) -> dict[int, dict]:
    """``{geom_id: GeoJSON geometry}`` for the requested features.

    Features whose simplified geometry collapsed to something empty or invalid
    are absent from the result rather than present with a null geometry --
    ``features.matviews`` drops those rows on purpose, and the callers here
    already handle a feature with no geometry.
    """
    if not fc_ids or not geom_ids:
        return {}

    table = pick_table(bbox if bbox is not None else bbox_for(geom_ids))
    with connection.cursor() as cursor:
        cursor.execute(
            _GEOJSON_SQL.format(table=table),
            [_COORD_PRECISION, fc_ids, geom_ids],
        )
        return {row[0]: json.loads(row[1]) for row in cursor.fetchall() if row[1]}
