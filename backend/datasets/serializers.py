from rest_framework import serializers

from .models import Dataset, DatasetResource


class DatasetResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DatasetResource
        fields = ["id", "name", "label", "path", "temporal"]


class DatasetSummarySerializer(serializers.ModelSerializer):
    bbox = serializers.SerializerMethodField()

    def get_bbox(self, obj):
        if obj.spatial_extent is None:
            return None
        xmin, ymin, xmax, ymax = obj.spatial_extent.extent
        return [xmin, ymin, xmax, ymax]

    class Meta:
        model = Dataset
        fields = [
            "id",
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


class DatasetDetailSerializer(serializers.ModelSerializer):
    resources = DatasetResourceSerializer(many=True, read_only=True)
    extract_types = serializers.SerializerMethodField()

    class Meta:
        model = Dataset
        fields = [
            "id",
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
            "resources",
            "extract_types",
        ]

    def get_extract_types(self, obj):
        pos = sorted(
            (po for po in obj.processing_options.all() if po.active and po.public),
            key=lambda po: po.short_name,
        )
        return [{"short_name": po.short_name, "description": po.description} for po in pos]
