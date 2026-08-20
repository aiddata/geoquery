from rest_framework import serializers

from datasets.models import Dataset
from features.models import FeatureCollection


class PublicDatasetSerializer(serializers.ModelSerializer):
    bbox = serializers.SerializerMethodField()

    def get_bbox(self, obj):
        if obj.spatial_extent is None:
            return None
        xmin, ymin, xmax, ymax = obj.spatial_extent.extent
        return [xmin, ymin, xmax, ymax]

    class Meta:
        model = Dataset
        fields = [
            "name",
            "title",
            "description",
            "type",
            "tags",
            "source_name",
            "source_url",
            "temporal_name",
            "temporal_type",
            "temporal_start",
            "temporal_end",
            "date_updated",
            "bbox",
        ]


class PublicDatasetCategorySerializer(serializers.Serializer):
    tag = serializers.CharField()
    display = serializers.CharField()


class PublicDatasetCoverageRequestSerializer(serializers.Serializer):
    """Documentation-only: describes the request body for @extend_schema.

    Not used for runtime validation — PublicDatasetCoverageView does its own
    manual isinstance check. featureIds is optional here to match that
    view's real behavior: a missing/empty list returns all active, public
    datasets rather than a 400.
    """

    featureIds = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )


class PublicBoundarySerializer(serializers.ModelSerializer):
    bbox = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()

    def get_bbox(self, obj):
        if obj.spatial_extent is None:
            return None
        xmin, ymin, xmax, ymax = obj.spatial_extent.extent
        return [xmin, ymin, xmax, ymax]

    def get_tags(self, obj):
        # Normalize null to [] to match features.views.FeatureCollectionAutocompleteView.
        return obj.tags or []

    class Meta:
        model = FeatureCollection
        fields = [
            "name",
            "title",
            "short_name",
            "description",
            "bbox",
            "group_name",
            "group_title",
            "group_class",
            "group_level",
            "source_name",
            "tags",
        ]


class PublicBoundaryPresetSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True, required=False)
    source_name = serializers.CharField(allow_null=True, required=False)
    group_class = serializers.CharField(allow_null=True, required=False)
    group_level = serializers.IntegerField(allow_null=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    sort_order = serializers.IntegerField(required=False)
