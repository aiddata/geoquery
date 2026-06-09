from pathlib import Path
import yaml
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FeatMap, FeatureCollection

_MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"


class FeatureCollectionAutocompleteView(generics.ListAPIView):
    """
    API endpoint for autocomplete functionality of feature collections.
    Returns a list of feature collection names matching the search query.

    Query parameters:
    - q: Search query string (searches in name, title, and description)
    - limit: Maximum number of results to return (default: 10; 0 = no limit)
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

        # Order by name and limit results (limit=0 means no limit)
        queryset = queryset.order_by("name")
        if limit > 0:
            queryset = queryset[:limit]

        # Return simplified data for autocomplete with grouping info
        results = [
            {
                "id": fc.id,
                "name": fc.name,
                "title": fc.title,
                "description": fc.description,
                "bbox": list(fc.spatial_extent.extent) if fc.spatial_extent else None,
                "group_name": fc.group_name,
                "group_title": fc.group_title,
                "group_class": fc.group_class,
                "group_level": fc.group_level,
                "source_name": fc.source_name,
                "tags": fc.tags or [],
                "date_added": fc.date_added.isoformat() if fc.date_added else None,
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
    Standard FCs use pre-simplified matviews. User-upload FCs use per-request
    dynamic simplification to avoid rebuilding shared matviews for unknown geometry.
    """
    is_upload = FeatureCollection.objects.filter(
        name=fc_name, is_user_upload=True
    ).exists()

    if is_upload:
        # Dynamic simplify at request time — tolerances match matview tiers
        if z <= 5:
            sql = _mvt_sql_dynamic_simplify(0.044)
        elif z <= 9:
            sql = _mvt_sql_dynamic_simplify(0.003)
        elif z <= 12:
            sql = _mvt_sql_dynamic_simplify(0.0003)
        else:
            sql = _mvt_sql_user_upload_raw()
    else:
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
    Exposes geom_id (Feature.id) as the tile feature id for client-side selection.
    """
    return f"""
        SELECT ST_AsMVT(mvtgeoms.*, %s) AS mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    sv.shape,
                    ST_TileEnvelope(%s, %s, %s),
                    4096, 256, true
                ) AS geom,
                sv.geom_id AS id,
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


class FeatureIdsView(APIView):
    """
    GET /api/features/ids/?fc=1,2,3

    Returns all Feature.ids belonging to the given FeatureCollection ids.
    Used by the frontend to resolve whole-FC selections to a flat feature list
    before submitting a request.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        fc_param = request.query_params.get("fc", "").strip()
        if not fc_param:
            return Response({"error": "fc parameter is required"}, status=400)

        try:
            fc_ids = [int(v) for v in fc_param.split(",") if v.strip()]
        except ValueError:
            return Response({"error": "fc must be a comma-separated list of integers"}, status=400)

        feature_ids = list(
            FeatMap.objects.filter(fc_id__in=fc_ids, fc__active=True, fc__public=True)
            .values_list("geom_id", flat=True)
            .distinct()
        )
        return Response({"featureIds": feature_ids})


class BoundaryPresetsView(APIView):
    """
    GET /api/features/presets/

    Returns boundary presets loaded from config/boundary_presets.yaml.
    Each preset defines filter criteria (group_class, group_level, tags) that
    the frontend can use to batch-select boundaries client-side.

    The YAML is cached but reloaded automatically when the file's mtime changes,
    so edits are picked up without restarting the backend.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    _presets_cache = None
    _cache_mtime = None

    @classmethod
    def _load_presets(cls):
        """Load boundary presets from YAML, reloading if the file has changed."""
        config_path = Path(__file__).parent.parent / "config" / "boundary_presets.yaml"
        try:
            current_mtime = config_path.stat().st_mtime
        except FileNotFoundError:
            cls._presets_cache = []
            cls._cache_mtime = None
            return cls._presets_cache

        if cls._presets_cache is not None and cls._cache_mtime == current_mtime:
            return cls._presets_cache

        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            cls._presets_cache = sorted(
                data.get("presets", []), key=lambda p: p.get("sort_order", 999)
            )
            cls._cache_mtime = current_mtime
            return cls._presets_cache

    def get(self, request):
        presets = self._load_presets()
        return Response(presets)


def _mvt_sql_raw():
    """SQL for generating MVT tiles from the raw (unsimplified) geometry.

    Exposes f.id (Feature.id) as the tile feature id for client-side selection.
    """
    return """
        SELECT ST_AsMVT(mvtgeoms.*, %s) AS mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(f.shape, 3857),
                    ST_TileEnvelope(%s, %s, %s),
                    4096, 256, true
                ) AS geom,
                f.id,
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


def _mvt_sql_dynamic_simplify(tolerance: float) -> str:
    """SQL for user-upload FCs: ST_Simplify applied per request at the given
    degree tolerance. Does not require public=True. No matview needed."""
    return f"""
        SELECT ST_AsMVT(mvtgeoms.*, %s) AS mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(ST_Simplify(f.shape, {tolerance}), 3857),
                    ST_TileEnvelope(%s, %s, %s),
                    4096, 256, true
                ) AS geom,
                f.id,
                fm.name
            FROM feat_map fm
            JOIN features f ON fm.geom_id = f.id
            WHERE fm.fc_id = (
                    SELECT id FROM feature_collections
                    WHERE name = %s AND active AND is_user_upload
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


def _mvt_sql_user_upload_raw() -> str:
    """Raw geometry for user-upload FCs at high zoom. Does not require public=True."""
    return """
        SELECT ST_AsMVT(mvtgeoms.*, %s) AS mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(f.shape, 3857),
                    ST_TileEnvelope(%s, %s, %s),
                    4096, 256, true
                ) AS geom,
                f.id,
                fm.name
            FROM feat_map fm
            JOIN features f ON fm.geom_id = f.id
            WHERE fm.fc_id = (
                    SELECT id FROM feature_collections
                    WHERE name = %s AND active AND is_user_upload
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
