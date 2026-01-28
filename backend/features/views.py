from django.db import connection
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import generics
from rest_framework.response import Response

from .models import FeatureCollection


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
            }
            for fc in queryset
        ]

        return Response(results)


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
    """

    # Verify feature collection exists and is accessible
    try:
        fc = FeatureCollection.objects.get(name=fc_name, active=True, public=True)
    except FeatureCollection.DoesNotExist:
        return HttpResponse("Feature collection not found", status=404)

    # SQL query to generate MVT tiles
    # Using ST_AsMVTGeom to convert geometries to tile coordinates
    # and ST_AsMVT to generate the final MVT format
    sql = """
        SELECT ST_AsMVT(mvtgeoms.*, %s) as mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(f.shape, 3857),
                    ST_TileEnvelope(%s, %s, %s),
                    4096,
                    256,
                    true
                ) AS geom,
                fm.id,
                fm.name,
                fm.attr
            FROM feat_map fm
            JOIN features f ON fm.geom_id = f.id
            WHERE fm.fc_id = %s
                AND ST_Intersects(
                    f.shape,
                    ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                )
        ) mvtgeoms
        WHERE mvtgeoms.geom IS NOT NULL
    """

    layer_name = fc_name
    params = [layer_name, z, x, y, fc.id, z, x, y]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        result = cursor.fetchone()

        if result and result[0]:
            # Return MVT binary data with appropriate content type
            return HttpResponse(
                bytes(result[0]), content_type="application/vnd.mapbox-vector-tile"
            )
        else:
            # Return empty tile if no features in this tile
            return HttpResponse(b"", content_type="application/vnd.mapbox-vector-tile")
