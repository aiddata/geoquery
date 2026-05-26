from rest_framework import serializers

from .models import Dataset, DatasetResource


class DatasetResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DatasetResource
        fields = ["id", "name", "label", "path", "temporal"]


class DatasetSummarySerializer(serializers.ModelSerializer):
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
        """Return active/public ProcessingOptions for raster datasets."""
        return list(
            obj.processing_options.filter(active=True, public=True)
            .order_by("short_name")
            .values("short_name", "description")
        )
