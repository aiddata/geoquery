from django.conf import settings
from django.db.models import Q
from django.utils.text import slugify
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.coverage import valid_coverage
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
    Returns global datasets, and datasets whose extent is confirmed (coverage
    status 1) to contain at least one of the given features. Coverage being
    recomputed after an extent or geometry change is not served; see
    analytics.coverage.valid_coverage.
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
                valid_coverage("replica")
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
    """The dataset category menu: settings.DATASET_CATEGORIES, in order.

    Each category is {tag, display, tags}: a stable key, its display name, and
    the dataset tags that put a dataset in it (any one is enough). Categories
    with no dataset visible to the caller are left out.
    """

    def list(self, request, *args, **kwargs):
        tags_in_use = set()
        for tag_list in (
            _replica_datasets(request.user)
            .exclude(tags__isnull=True)
            .values_list("tags", flat=True)
        ):
            tags_in_use.update(t.lower() for t in tag_list)

        categories = []
        for display, tags in settings.DATASET_CATEGORIES.items():
            wanted = [t.lower() for t in tags]
            if tags_in_use.intersection(wanted):
                categories.append({"tag": slugify(display).replace("-", "_"), "display": display, "tags": wanted})
        return Response(categories)
