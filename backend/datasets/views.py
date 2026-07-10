from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Coverage

from .models import Dataset
from .serializers import DatasetDetailSerializer, DatasetSummarySerializer


class DatasetListView(generics.ListAPIView):
    """List all active/public datasets with no feature filtering."""

    serializer_class = DatasetSummarySerializer

    def get_queryset(self):
        return Dataset.objects.filter(active=True, public=True).order_by("type", "-date_updated")

    def list(self, request, *args, **kwargs):
        """Return a flat list (no pagination wrapper) to match the frontend expectation."""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class DatasetCoverageView(APIView):
    """POST /api/datasets/coverage/

    Body: {"featureIds": [1, 2, 3, ...]}
    Returns datasets that have at least one Coverage record for any of the given features.
    Accepts a POST body instead of query params to avoid URL length limits for large selections.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        feature_ids = request.data.get("featureIds", [])
        if not isinstance(feature_ids, list) or not all(isinstance(i, int) for i in feature_ids):
            return Response({"error": "featureIds must be a list of integers"}, status=400)

        qs = Dataset.objects.filter(active=True, public=True)

        if feature_ids:
            covered_ids = (
                Coverage.objects.filter(geom_id__in=feature_ids)
                .values_list("dataset_id", flat=True)
                .distinct()
            )
            qs = qs.filter(id__in=covered_ids)

        qs = qs.order_by("type", "-date_updated")
        return Response(DatasetSummarySerializer(qs, many=True).data)


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
