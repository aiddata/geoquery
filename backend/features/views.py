from django.db import connection
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import generics
from rest_framework.response import Response

from .models import FeatureCollection

_MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"


class FeatureCollectionAutocompleteView(generics.ListAPIView):
    """
    API endpoint for autocomplete functionality of feature collections.
    Returns a list of feature collection names matching the search query.

    Query parameters:
    - q: Search query string (searches in name, title, and description)
    - limit: Maximum number of results to return (default: 10)
    """

    def get(self, request, *args, **kwargs):
        query = request.query_params.get("q", "").strip()
        limit = int(request.query_params.get("limit", 10))

        # Start with active and public feature collections
        queryset = FeatureCollection.objects.filter(active=True, public=True)

        # Apply search filter if query is provided
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(title__icontains=query)
                | Q(description__icontains=query)
            )

        # Order by name and limit results
        queryset = queryset.order_by("name")[:limit]

        # Return simplified data for autocomplete
        results = [
            {
                "id": fc.id,
                "name": fc.name,
                "title": fc.title,
                "description": fc.description,
                "bbox": list(fc.spatial_extent.extent) if fc.spatial_extent else None,
            }
            for fc in queryset
        ]

        return Response(results)


def feature_collection_vector_tiles(request, fc_name, z, x, y):
    """
    Return MVT vector tiles for a given feature collection.

    URL parameters:
    - fc_name: Name of the feature collection
    - z, x, y: Tile coordinates (zoom, x, y)

    Returns Mapbox Vector Tile (MVT) format for use with MapLibre GL JS.
    Uses pre-simplified geometries at lower zoom levels for performance.
    """

    # Choose the geometry source based on zoom level
    if z <= 5:
        sql = _mvt_sql_simplified("features_simplified_z0_5")
    elif z <= 9:
        sql = _mvt_sql_simplified("features_simplified_z6_9")
    elif z <= 12:
        sql = _mvt_sql_simplified("features_simplified_z10_12")
    else:
        sql = _mvt_sql_raw()

    # Param order: layer_name, z/x/y (AsMVTGeom), fc_name, z/x/y (&&), z/x/y (Intersects)
    params = [fc_name, z, x, y, fc_name, z, x, y, z, x, y]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        result = cursor.fetchone()

        if result and result[0]:
            return HttpResponse(bytes(result[0]), content_type=_MVT_CONTENT_TYPE)
        else:
            return HttpResponse(b"", content_type=_MVT_CONTENT_TYPE)


def _mvt_sql_simplified(view_name):
    """SQL for generating MVT tiles from a simplified materialized view.

    Matview geometry is stored in EPSG:3857, so no per-row ST_Transform needed.
    ST_TileEnvelope already returns 3857, used directly for both clipping and filtering.
    """
    return f"""
        SELECT ST_AsMVT(mvtgeoms.*, %s) AS mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    sv.shape,
                    ST_TileEnvelope(%s, %s, %s),
                    4096, 256, true
                ) AS geom,
                sv.fm_id AS id,
                sv.name,
                sv.attr
            FROM {view_name} sv
            WHERE sv.fc_id = (
                    SELECT id FROM feature_collections
                    WHERE name = %s AND active AND public
                    LIMIT 1
                )
                AND sv.shape && ST_TileEnvelope(%s, %s, %s)
                AND ST_Intersects(sv.shape, ST_TileEnvelope(%s, %s, %s))
        ) mvtgeoms
        WHERE mvtgeoms.geom IS NOT NULL
    """


def _mvt_sql_raw():
    """SQL for generating MVT tiles from the raw (unsimplified) geometry."""
    return """
        SELECT ST_AsMVT(mvtgeoms.*, %s) AS mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(f.shape, 3857),
                    ST_TileEnvelope(%s, %s, %s),
                    4096, 256, true
                ) AS geom,
                fm.id,
                fm.name,
                fm.attr
            FROM feat_map fm
            JOIN features f ON fm.geom_id = f.id
            WHERE fm.fc_id = (
                    SELECT id FROM feature_collections
                    WHERE name = %s AND active AND public
                    LIMIT 1
                )
                AND f.shape && ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                AND ST_Intersects(
                    f.shape,
                    ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                )
        ) mvtgeoms
        WHERE mvtgeoms.geom IS NOT NULL
    """
