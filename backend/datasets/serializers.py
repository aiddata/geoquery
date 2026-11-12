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
            "license",
            "license_url",
            "citation",
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
    # Shown in the dataset page's metadata panel. Resolution and version live
    # in ``other`` alongside filters and outcomes.
    resolution = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField()

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
            "license",
            "license_url",
            "citation",
            "temporal_name",
            "temporal_type",
            "temporal_start",
            "temporal_end",
            "date_updated",
            "date_added",
            "details",
            "variable_description",
            "is_global",
            "resolution",
            "version",
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

    def _other(self, obj, key):
        if obj.other and isinstance(obj.other, dict):
            return obj.other.get(key)
        return None

    def get_resolution(self, obj):
        """Cell size in decimal degrees, or None when unknown.

        Stored as a string ("0.008333333333333"), and blank for a few
        datasets, so anything that is not a positive number is reported as
        unknown rather than passed through for the page to guess at.
        """
        try:
            value = float(self._other(obj, "resolution"))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def get_version(self, obj):
        version = self._other(obj, "version")
        if version is None:
            return None
        return str(version).strip() or None
