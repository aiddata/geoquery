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
    fields_ = serializers.SerializerMethodField("get_fields_data")
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
            "fields_",
            "extract_types",
        ]

    def to_representation(self, instance):
        """Rename fields_ -> fields in the output."""
        data = super().to_representation(instance)
        data["fields"] = data.pop("fields_")
        return data

    def get_fields_data(self, obj):
        """Build the fields dict for release datasets from the `other` JSON field.

        Expected format in obj.other:
        {
            "fields": {
                "field_name": {
                    "display": "Human Label",
                    "type": "list" | "slider",
                    "is_default": true/false
                },
                ...
            }
        }

        For list-type fields, distinct values come from Mapping entries.
        For slider-type fields, distinct is [min, max] from Mapping entries.
        """
        if obj.type != "release":
            return {}

        other = obj.other or {}
        field_defs = other.get("fields", {})
        if not field_defs:
            return {}

        # Pre-fetch all mappings for this dataset
        mappings = obj.mappings.all().order_by("map_val")

        result = {}
        for field_name, field_meta in field_defs.items():
            field_type = field_meta.get("type", "list")
            is_default = field_meta.get("is_default", False)
            display = field_meta.get("display", field_name)

            if field_type == "slider":
                vals = [m.map_val for m in mappings if m.map_name == field_name]
                distinct = [min(vals), max(vals)] if vals else [0, 0]
            else:
                distinct = [m.map_name for m in mappings if m.map_name is not None]

            result[field_name] = {
                "name": field_name,
                "display": display,
                "type": field_type,
                "is_default": is_default,
                "distinct": distinct,
            }

        return result

    def get_extract_types(self, obj):
        """Return active/public ProcessingOptions for raster datasets."""
        if obj.type != "raster":
            return []
        return list(
            obj.processing_options.filter(active=True, public=True)
            .order_by("short_name")
            .values("short_name", "description")
        )
