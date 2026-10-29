from pathlib import Path
import yaml
from django.db import connections
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils.cache import patch_vary_headers
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.access import (
    resolve_feature_collection_for_tiles,
    resolve_feature_collections_for_tiles,
    visible_feature_collections,
)

from .models import FeatMap, FeatureCollection

_MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"

# MVT layer name of the multi-collection endpoint. The frontend matches on it
# via `source-layer` (MULTI_TILE_LAYER in frontend/src/lib/api.ts).
MULTI_TILE_LAYER = "boundaries"

# Every collection in the catalog fits (719 today), and the comma-separated
# list stays well under nginx's 8 KB request line.
MAX_MULTI_TILE_FCS = 1000


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
        try:
            limit = int(request.query_params.get("limit", 10))
        except (ValueError, TypeError):
            return Response(
                {"error": "limit must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Start with the collections visible to the caller. User uploads are
        # never public so they are already excluded, but say so explicitly: an
        # ephemeral upload must not become selectable just because someone
        # added it to a catalog.
        queryset = visible_feature_collections(
            request.user, FeatureCollection.objects.using("replica")
        ).filter(is_user_upload=False)

        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(title__icontains=query)
                | Q(description__icontains=query)
            )
        queryset = queryset.order_by("name")

        # Limit results (limit=0 means no limit)
        if limit > 0:
            queryset = queryset[:limit]

        # Return simplified data for autocomplete with grouping info
        results = [
            {
                "id": fc.id,
                "name": fc.name,
                "title": fc.title,
                "short_name": fc.short_name,
                "description": fc.description,
                "bbox": list(fc.spatial_extent.extent) if fc.spatial_extent else None,
                "group_name": fc.group_name,
                "group_title": fc.group_title,
                "group_class": fc.group_class,
                "group_level": fc.group_level,
                "source_name": fc.source_name,
                "source_url": fc.source_url,
                "license": fc.license,
                "license_url": fc.license_url,
                "citation": fc.citation,
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

    Visibility is resolved in Python (see catalog.access) rather than in the
    SQL, so the tile builders take a resolved fc id. This costs no extra query:
    it replaces the is_user_upload probe this view already ran, and removes the
    correlated subquery from each statement.
    """
    fc = resolve_feature_collection_for_tiles(request.user, fc_name)
    if fc is None:
        # An empty tile rather than a 404: it is byte-for-byte what an unknown
        # name produced before this change, and it keeps MapLibre from logging
        # an error for every tile in the viewport.
        return HttpResponse(b"", content_type=_MVT_CONTENT_TYPE)

    if fc.is_user_upload:
        # Dynamic simplify at request time. The z<=5 tier uses a finer
        # tolerance than the matview equivalent because custom requests
        # typically render fewer / smaller features, so the per-tile vertex
        # budget can afford more detail without hurting render performance.
        if z <= 5:
            sql = _mvt_sql_dynamic_simplify(0.01)
        elif z <= 9:
            sql = _mvt_sql_dynamic_simplify(0.003)
        elif z <= 12:
            sql = _mvt_sql_dynamic_simplify(0.0003)
        else:
            sql = _mvt_sql_user_upload_raw()
    else:
        table = _simplified_table_for_zoom(z)
        sql = _mvt_sql_simplified(table) if table else _mvt_sql_raw()

    # Param order: layer_name, z/x/y (AsMVTGeom), fc_id, z/x/y (&&), z/x/y (Intersects).
    # The first param stays the *name*: it is the MVT layer name, which the
    # frontend matches on via `source-layer`. Only the WHERE param is an id.
    params = [fc_name, z, x, y, fc.id, z, x, y, z, x, y]

    # The visibility resolution above deliberately stays on the primary so a
    # freshly revoked catalog grant takes effect immediately; only the bulk
    # geometry read -- by far the hottest query in the app -- goes to a standby.
    with connections["replica"].cursor() as cursor:
        cursor.execute(sql, params)
        result = cursor.fetchone()

    body = bytes(result[0]) if result and result[0] else b""
    response = HttpResponse(body, content_type=_MVT_CONTENT_TYPE)
    if not fc.public:
        # Behind a shared cache, one caller's permissioned tile must never be
        # served to another.
        response["Cache-Control"] = "private, no-store"
        patch_vary_headers(response, ["Cookie"])
    return response


def multi_feature_collection_vector_tiles(request, z, x, y):
    """
    Return one MVT tile covering several feature collections at once.

    Query parameters:
    - fc: comma-separated FeatureCollection ids

    All features go into a single layer, MULTI_TILE_LAYER, each carrying `id`
    (Feature.id), `fc_id` and `name`, so the map styles the selection with one
    source and data-driven expressions instead of a source per collection.

    Ids the caller may not see are dropped, as are user uploads (see
    catalog.access.resolve_feature_collections_for_tiles).
    """
    raw = request.GET.get("fc", "").strip()
    if not raw:
        return HttpResponseBadRequest("fc parameter is required")
    try:
        requested = sorted({int(v) for v in raw.split(",") if v.strip()})
    except ValueError:
        return HttpResponseBadRequest("fc must be a comma-separated list of integers")
    if not requested:
        return HttpResponseBadRequest("fc parameter is required")
    if len(requested) > MAX_MULTI_TILE_FCS:
        return HttpResponseBadRequest(
            f"fc may list at most {MAX_MULTI_TILE_FCS} feature collections"
        )

    fcs = resolve_feature_collections_for_tiles(request.user, requested)

    if fcs:
        table = _simplified_table_for_zoom(z)
        sql = _mvt_sql_multi(table) if table else _mvt_sql_multi_raw()
        # Param order: layer_name, z/x/y (AsMVTGeom), fc_ids, z/x/y (&&), z/x/y (Intersects).
        params = [MULTI_TILE_LAYER, z, x, y, [fc.id for fc in fcs], z, x, y, z, x, y]
        with connections["replica"].cursor() as cursor:
            cursor.execute(sql, params)
            result = cursor.fetchone()
        body = bytes(result[0]) if result and result[0] else b""
    else:
        body = b""

    response = HttpResponse(body, content_type=_MVT_CONTENT_TYPE)
    # The tile is the same for every caller only when every requested id is a
    # public collection. Otherwise its content depends on the caller's grants
    # -- a granted private collection is in it, an ungranted one is silently
    # missing -- so no shared cache may store it.
    public_ids = {fc.id for fc in fcs if fc.public}
    if len(public_ids) < len(requested):
        response["Cache-Control"] = "private, no-store"
        patch_vary_headers(response, ["Cookie"])
    return response


_SIMPLIFIED_VIEWS = frozenset({
    "features_simplified_z0_5",
    "features_simplified_z6_9",
    "features_simplified_z10_12",
})


def _simplified_table_for_zoom(z):
    """Pre-simplified geometry table for zoom z, or None above z12, where
    tiles come from the raw geometry instead."""
    if z <= 5:
        return "features_simplified_z0_5"
    if z <= 9:
        return "features_simplified_z6_9"
    if z <= 12:
        return "features_simplified_z10_12"
    return None


def _mvt_sql_multi(view_name):
    """Like _mvt_sql_simplified, for a list of fc ids. One layer for all of
    them, with fc_id so the frontend can style per collection; no attr.

    fc_id = ANY(...) together with the envelope test is a bitmap scan on the
    (fc_id, shape) GiST index. Measured on a copy of production's z0_5 table,
    joining unnest(ids) instead was never meaningfully faster, and for large
    selections it planned a nested loop per collection, up to 250x slower.
    """
    assert view_name in _SIMPLIFIED_VIEWS, f"Unknown simplified view: {view_name!r}"
    return f"""
        SELECT ST_AsMVT(mvtgeoms.*, %s) AS mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    sv.shape,
                    ST_TileEnvelope(%s, %s, %s),
                    4096, 256, true
                ) AS geom,
                sv.geom_id AS id,
                sv.fc_id,
                sv.name
            FROM {view_name} sv
            WHERE sv.fc_id = ANY(%s)
                AND sv.shape && ST_TileEnvelope(%s, %s, %s)
                AND ST_Intersects(sv.shape, ST_TileEnvelope(%s, %s, %s))
        ) mvtgeoms
        WHERE mvtgeoms.geom IS NOT NULL
    """


def _mvt_sql_multi_raw():
    """Like _mvt_sql_raw, for a list of fc ids (see _mvt_sql_multi)."""
    return """
        SELECT ST_AsMVT(mvtgeoms.*, %s) AS mvt FROM (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(f.shape, 3857),
                    ST_TileEnvelope(%s, %s, %s),
                    4096, 256, true
                ) AS geom,
                f.id,
                fm.fc_id,
                fm.name
            FROM feat_map fm
            JOIN features f ON fm.geom_id = f.id
            WHERE fm.fc_id = ANY(%s)
                AND f.shape && ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                AND ST_Intersects(
                    f.shape,
                    ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                )
        ) mvtgeoms
        WHERE mvtgeoms.geom IS NOT NULL
    """


def _mvt_sql_simplified(view_name):
    assert view_name in _SIMPLIFIED_VIEWS, f"Unknown simplified view: {view_name!r}"
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
            WHERE sv.fc_id = %s
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

    # Authentication left at the project default so catalog grants resolve.
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
            FeatMap.objects.using("replica")
            .filter(
                fc__in=visible_feature_collections(
                    request.user, FeatureCollection.objects.using("replica")
                ).filter(id__in=fc_ids)
            )
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
        """Load boundary presets from YAML, reloading if the file has changed.

        Also called directly by public_api.views.PublicBoundaryPresetsView —
        changing this method's signature or return shape affects that
        external consumer too.
        """
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
            WHERE fm.fc_id = %s
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
    degree tolerance. No matview needed. Takes a resolved fc id -- visibility
    is decided by the caller (see catalog.access)."""
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
            WHERE fm.fc_id = %s
                AND f.shape && ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                AND ST_Intersects(
                    f.shape,
                    ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                )
        ) mvtgeoms
        WHERE mvtgeoms.geom IS NOT NULL
    """


def _mvt_sql_user_upload_raw() -> str:
    """Raw geometry for user-upload FCs at high zoom. Takes a resolved fc id --
    visibility is decided by the caller (see catalog.access)."""
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
            WHERE fm.fc_id = %s
                AND f.shape && ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                AND ST_Intersects(
                    f.shape,
                    ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                )
        ) mvtgeoms
        WHERE mvtgeoms.geom IS NOT NULL
    """
