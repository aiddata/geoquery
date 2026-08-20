from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .base import StacApiBaseMixin
from .serializers import CollectionSerializer, ItemSerializer
from .sources import all_collection_sources, get_collection_source, get_item, get_items_for_collection
from .utils import STAC_VERSION, build_url

# Only conformance classes actually implemented. No filter/CQL2, fields,
# sort, or transaction extensions.
STAC_CONFORMANCE_CLASSES = [
    "https://api.stacspec.org/v1.0.0/core",
    "https://api.stacspec.org/v1.0.0/collections",
    "https://api.stacspec.org/v1.0.0/ogcapi-features",
    "https://api.stacspec.org/v1.0.0/item-search",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
]


class StacLandingPageView(StacApiBaseMixin, APIView):
    """GET /api/stac/v1/ — STAC Catalog / OGC API landing page."""

    def get(self, request):
        return Response(
            {
                "type": "Catalog",
                "stac_version": STAC_VERSION,
                "id": "geoquery-stac",
                "title": "GeoQuery STAC Catalog",
                "description": "Discovery catalog for GeoQuery datasets and boundaries.",
                "conformsTo": STAC_CONFORMANCE_CLASSES,
                "links": [
                    {"rel": "self", "href": build_url(request, "/api/stac/v1/"), "type": "application/json"},
                    {"rel": "root", "href": build_url(request, "/api/stac/v1/"), "type": "application/json"},
                    {
                        "rel": "conformance",
                        "href": build_url(request, "/api/stac/v1/conformance/"),
                        "type": "application/json",
                    },
                    {"rel": "data", "href": build_url(request, "/api/stac/v1/collections/"), "type": "application/json"},
                    {"rel": "search", "href": build_url(request, "/api/stac/v1/search/"), "type": "application/geo+json"},
                    {"rel": "service-doc", "href": build_url(request, "/api/stac/v1/docs/"), "type": "text/html"},
                ],
            }
        )


class StacConformanceView(StacApiBaseMixin, APIView):
    """GET /api/stac/v1/conformance/"""

    def get(self, request):
        return Response({"conformsTo": STAC_CONFORMANCE_CLASSES})


class StacCollectionListView(StacApiBaseMixin, APIView):
    """GET /api/stac/v1/collections/"""

    def get(self, request):
        sources = all_collection_sources()
        serializer = CollectionSerializer(sources, many=True, context={"request": request})
        return Response(
            {
                "collections": serializer.data,
                "links": [
                    {
                        "rel": "self",
                        "href": build_url(request, "/api/stac/v1/collections/"),
                        "type": "application/json",
                    }
                ],
            }
        )


class StacCollectionDetailView(StacApiBaseMixin, APIView):
    """GET /api/stac/v1/collections/{name}/"""

    def get(self, request, name):
        source = get_collection_source(name)
        if source is None:
            raise NotFound(f"No such collection: {name}")
        serializer = CollectionSerializer(source, context={"request": request})
        return Response(serializer.data)


DEFAULT_ITEM_PAGE_SIZE = 100


class StacItemListView(StacApiBaseMixin, APIView):
    """GET /api/stac/v1/collections/{name}/items/?limit=&offset="""

    def get(self, request, name):
        source = get_collection_source(name)
        if source is None:
            raise NotFound(f"No such collection: {name}")

        try:
            limit = int(request.query_params.get("limit", DEFAULT_ITEM_PAGE_SIZE))
            offset = int(request.query_params.get("offset", 0))
        except (TypeError, ValueError):
            raise ValidationError({"limit/offset": "must be integers"})

        items = get_items_for_collection(source)
        page = items[offset : offset + limit]
        serializer = ItemSerializer(page, many=True, context={"request": request})

        links = [
            {
                "rel": "self",
                "href": build_url(request, f"/api/stac/v1/collections/{name}/items/"),
                "type": "application/geo+json",
            }
        ]
        if offset + limit < len(items):
            next_href = build_url(
                request, f"/api/stac/v1/collections/{name}/items/?limit={limit}&offset={offset + limit}"
            )
            links.append({"rel": "next", "href": next_href, "type": "application/geo+json"})

        return Response(
            {
                "type": "FeatureCollection",
                "stac_version": STAC_VERSION,
                "features": serializer.data,
                "links": links,
                "numberMatched": len(items),
                "numberReturned": len(page),
            }
        )


class StacItemDetailView(StacApiBaseMixin, APIView):
    """GET /api/stac/v1/collections/{name}/items/{item_id}/"""

    def get(self, request, name, item_id):
        source = get_collection_source(name)
        if source is None:
            raise NotFound(f"No such collection: {name}")
        item = get_item(source, item_id)
        if item is None:
            raise NotFound(f"No such item: {item_id}")
        serializer = ItemSerializer(item, context={"request": request})
        return Response(serializer.data)
