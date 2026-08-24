from rest_framework import serializers

from catalog.access import filter_processing_options

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
            "processing_class",
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
    filters = serializers.SerializerMethodField()
    outcomes = serializers.SerializerMethodField()

    class Meta:
        model = Dataset
        fields = [
            "id",
            "name",
            "title",
            "description",
            "type",
            "processing_class",
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
            "filters",
            "outcomes",
        ]

    def get_extract_types(self, obj):
        # `.all()` returns the list cached by DatasetDetailView's prefetch;
        # chaining `.filter()` onto the related manager would re-query and
        # defeat it, so filter_processing_options iterates in Python instead.
        # A bare DatasetDetailSerializer(obj) with no request context degrades
        # to public-only rather than raising.
        request = self.context.get("request")
        pos = sorted(
            filter_processing_options(
                getattr(request, "user", None), obj.processing_options.all()
            ),
            key=lambda po: po.short_name,
        )
        return [{"short_name": po.short_name, "description": po.description} for po in pos]

    def get_filters(self, obj):
        if obj.other and isinstance(obj.other, dict):
            return obj.other.get("filters")
        return None

    def get_outcomes(self, obj):
        if obj.other and isinstance(obj.other, dict):
            return obj.other.get("outcomes")
        return None
