from rest_framework import serializers

from .sources import is_feature_collection
from .utils import STAC_VERSION, bbox_from_geometry, build_url, to_rfc3339

WORLD_BBOX = [-180.0, -90.0, 180.0, 90.0]


def _providers(obj):
    if not obj.source_name:
        return []
    provider = {"name": obj.source_name}
    if obj.source_url:
        provider["url"] = obj.source_url
    return [provider]


class CollectionSerializer(serializers.Serializer):
    """Serializes a Dataset or FeatureCollection into a STAC Collection.

    Both models expose the same field names for everything except
    summaries (FeatureCollection-only: group_class/group_level), so one
    to_representation handles both via plain attribute access rather than
    two near-duplicate serializer classes.
    """

    def to_representation(self, obj):
        request = self.context["request"]
        bbox = bbox_from_geometry(obj.spatial_extent)
        data = {
            "type": "Collection",
            "stac_version": STAC_VERSION,
            "id": obj.name,
            "title": obj.title or obj.name,
            "description": obj.description or obj.title or obj.name,
            "license": "See source",
            "keywords": obj.tags or [],
            "providers": _providers(obj),
            "extent": {
                "spatial": {"bbox": [bbox or WORLD_BBOX]},
                "temporal": {
                    "interval": [[to_rfc3339(obj.temporal_start), to_rfc3339(obj.temporal_end)]]
                },
            },
            "links": [
                {
                    "rel": "self",
                    "href": build_url(request, f"/api/stac/v1/collections/{obj.name}/"),
                    "type": "application/json",
                },
                {
                    "rel": "items",
                    "href": build_url(request, f"/api/stac/v1/collections/{obj.name}/items/"),
                    "type": "application/geo+json",
                },
                {"rel": "parent", "href": build_url(request, "/api/stac/v1/"), "type": "application/json"},
                {"rel": "root", "href": build_url(request, "/api/stac/v1/"), "type": "application/json"},
            ],
        }
        if is_feature_collection(obj):
            summaries = {}
            if obj.group_class:
                summaries["group_class"] = [obj.group_class]
            if obj.group_level is not None:
                summaries["group_level"] = [obj.group_level]
            if summaries:
                data["summaries"] = summaries
        return data
