from rest_framework import serializers

from datasets.models import Dataset


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
    featureIds = serializers.ListField(child=serializers.IntegerField())
