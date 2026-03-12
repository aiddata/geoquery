from django.db.models import Q
from rest_framework import generics
from rest_framework.response import Response

from features.models import FeatureCollection

from .models import Dataset
from .serializers import DatasetDetailSerializer, DatasetSummarySerializer


class DatasetListView(generics.ListAPIView):
    """List datasets relevant to a given boundary.

    Query parameters:
    - boundary: FeatureCollection name (required). Returns datasets whose
      spatial_extent intersects the boundary, plus any global datasets.
    """

    serializer_class = DatasetSummarySerializer

    def get_queryset(self):
        qs = Dataset.objects.filter(active=True, public=True)

        boundary_name = self.request.query_params.get("boundary")
        if boundary_name:
            try:
                fc = FeatureCollection.objects.get(
                    name=boundary_name, active=True, public=True
                )
            except FeatureCollection.DoesNotExist:
                return qs.none()

            if fc.spatial_extent:
                qs = qs.filter(
                    Q(is_global=True) | Q(spatial_extent__intersects=fc.spatial_extent)
                )
            else:
                # Boundary has no geometry — fall back to global datasets only
                qs = qs.filter(is_global=True)
        else:
            # No boundary specified — return all active/public datasets
            pass

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
            "resources", "mappings"
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
