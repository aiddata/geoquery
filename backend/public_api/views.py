from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Coverage
from datasets.models import Dataset

from .base import PublicApiBaseMixin
from .serializers import (
    PublicDatasetCategorySerializer,
    PublicDatasetCoverageRequestSerializer,
    PublicDatasetSerializer,
)


class PublicDatasetListView(PublicApiBaseMixin, generics.ListAPIView):
    """GET /api/public/v1/datasets/ — flat list of active, public datasets."""

    serializer_class = PublicDatasetSerializer

    def get_queryset(self):
        return Dataset.objects.filter(active=True, public=True).order_by("type", "-date_updated")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class PublicDatasetDetailView(PublicApiBaseMixin, generics.RetrieveAPIView):
    """GET /api/public/v1/datasets/{name}/ — a single dataset by name."""

    serializer_class = PublicDatasetSerializer
    lookup_field = "name"

    def get_queryset(self):
        return Dataset.objects.filter(active=True, public=True)


class PublicDatasetCategoryView(PublicApiBaseMixin, generics.ListAPIView):
    """GET /api/public/v1/datasets/categories/ — deduplicated dataset tags."""

    serializer_class = PublicDatasetCategorySerializer

    def list(self, request, *args, **kwargs):
        tags = (
            Dataset.objects.filter(active=True, public=True)
            .exclude(tags__isnull=True)
            .exclude(tags=[])
            .values_list("tags", flat=True)
        )

        seen = set()
        categories = []
        for tag_list in tags:
            for tag in tag_list:
                if tag not in seen:
                    seen.add(tag)
                    categories.append({"tag": tag, "display": tag.replace("_", " ").title()})

        categories.sort(key=lambda c: c["display"])
        return Response(categories)


class PublicDatasetCoverageView(PublicApiBaseMixin, APIView):
    """POST /api/public/v1/datasets/coverage/

    Body: {"featureIds": [1, 2, 3, ...]}
    Returns datasets confirmed (status=1) to cover at least one of the given
    boundary IDs. POST (not GET) to avoid URL length limits for large
    selections, matching the internal datasets/coverage/ endpoint.

    Coverage rows start at status=-1 (untested) the moment a feature or
    dataset is created — see datasets.signals.on_dataset_created and
    features.signals.on_feature_created — and are only flipped to 0/1 once
    the async ST_Contains check runs. Filtering on status=1 here (rather
    than matching any row, untested included) is what makes "covers this
    boundary" mean something.
    """

    @extend_schema(
        request=PublicDatasetCoverageRequestSerializer,
        responses=PublicDatasetSerializer(many=True),
    )
    def post(self, request):
        feature_ids = request.data.get("featureIds", [])
        if not isinstance(feature_ids, list) or not all(isinstance(i, int) for i in feature_ids):
            raise ValidationError({"featureIds": "must be a list of integers"})

        qs = Dataset.objects.filter(active=True, public=True)
        if feature_ids:
            covered_ids = (
                Coverage.objects.filter(geom_id__in=feature_ids, status=1)
                .values_list("dataset_id", flat=True)
                .distinct()
            )
            qs = qs.filter(id__in=covered_ids)

        qs = qs.order_by("type", "-date_updated")
        return Response(PublicDatasetSerializer(qs, many=True).data)
