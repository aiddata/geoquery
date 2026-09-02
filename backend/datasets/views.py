from django.db.models import Q
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Coverage
from catalog.access import visible_datasets

from .models import Dataset
from .serializers import DatasetDetailSerializer, DatasetSummarySerializer


def _replica_datasets(user):
    """Catalog reads off the standby.

    Datasets and their catalog membership are written by admins and the ingest
    command, never by the request path, so nothing here is read-after-write.
    """
    return visible_datasets(user, Dataset.objects.using("replica"))


class DatasetListView(generics.ListAPIView):
    """List the datasets visible to the caller, with no feature filtering."""

    serializer_class = DatasetSummarySerializer

    def get_queryset(self):
        return _replica_datasets(self.request.user).order_by("type", "-date_updated")

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

    # Authentication is left at the project default (SessionAuthentication) so
    # catalog grants can be resolved; AllowAny keeps anonymous POSTs working.
    # Note DRF enforces CSRF on this endpoint for logged-in users only, so the
    # frontend must call it through apiFetch.
    permission_classes = [AllowAny]

    def post(self, request):
        feature_ids = request.data.get("featureIds", [])
        if not isinstance(feature_ids, list) or not all(isinstance(i, int) for i in feature_ids):
            return Response({"error": "featureIds must be a list of integers"}, status=400)

        qs = _replica_datasets(request.user)

        if feature_ids:
            covered_ids = (
                Coverage.objects.using("replica")
                .filter(geom_id__in=feature_ids)
                .values_list("dataset_id", flat=True)
                .distinct()
            )
            qs = qs.filter(Q(is_global=True) | Q(id__in=covered_ids))

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
        # A dataset the caller may not see 404s rather than 403s, so the detail
        # endpoint cannot be used to enumerate private dataset names.
        return _replica_datasets(self.request.user).prefetch_related(
            "resources", "mappings", "processing_options"
        )


class DatasetCategoryView(generics.ListAPIView):
    """Return the distinct dataset tag categories.

    Returns a list of {tag, display} objects derived from the tags
    ArrayField across every dataset visible to the caller.
    """

    def list(self, request, *args, **kwargs):
        tags = (
            _replica_datasets(request.user)
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
