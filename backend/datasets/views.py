from rest_framework import generics
from rest_framework.response import Response

from analytics.models import Coverage

from .models import Dataset
from .serializers import DatasetDetailSerializer, DatasetSummarySerializer


class DatasetListView(generics.ListAPIView):
    """List datasets with coverage for a set of features.

    Query parameters:
    - features: Comma-separated Feature.id values. Returns only datasets that
      have at least one Coverage record for any of the given features.
    """

    serializer_class = DatasetSummarySerializer

    def get_queryset(self):
        qs = Dataset.objects.filter(active=True, public=True)

        features_param = self.request.query_params.get("features", "").strip()
        if features_param:
            try:
                feature_ids = [int(v) for v in features_param.split(",") if v.strip()]
            except ValueError:
                return qs.none()

            if not feature_ids:
                return qs.none()

            covered_ids = (
                Coverage.objects.filter(geom_id__in=feature_ids)
                .values_list("dataset_id", flat=True)
                .distinct()
            )
            qs = qs.filter(id__in=covered_ids)

        return qs.order_by("type", "-date_updated")

    def list(self, request, *args, **kwargs):
        """Return a flat list (no pagination wrapper) to match the frontend expectation."""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class DatasetDetailView(generics.RetrieveAPIView):
    """Retrieve full detail for a single dataset by name.

    URL parameter:
    - name: Dataset name (slug)

    Query parameters:
    - boundary: FeatureCollection name (currently unused, reserved for
      future boundary-specific field filtering)
    """

    serializer_class = DatasetDetailSerializer
    lookup_field = "name"

    def get_queryset(self):
        return Dataset.objects.filter(active=True, public=True).prefetch_related(
            "resources", "mappings", "processing_options"
        )


class DatasetCategoryView(generics.ListAPIView):
    """Return the distinct dataset tag categories.

    Returns a list of {tag, display} objects derived from the tags
    ArrayField across all active/public datasets.
    """

    def list(self, request, *args, **kwargs):
        tags = (
            Dataset.objects.filter(active=True, public=True)
            .exclude(tags__isnull=True)
            .exclude(tags=[])
            .values_list("tags", flat=True)
        )

        # Flatten and deduplicate
        seen = set()
        categories = []
        for tag_list in tags:
            for tag in tag_list:
                if tag not in seen:
                    seen.add(tag)
                    categories.append(
                        {"tag": tag, "display": tag.replace("_", " ").title()}
                    )

        categories.sort(key=lambda c: c["display"])
        return Response(categories)
