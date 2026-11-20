"""Public stats endpoints (GEO-98): the figures on GeoQuery's /stats page.

The summary and time series come from the hourly snapshot the page reads
(stats.builder), reshaped into a stable public form, so changes to the page's
own payload don't break sites showing these figures. Neither runs a query
against the snapshot's sources: an unbuilt snapshot is a 503, never the slow
live build the internal endpoint falls back to. The status is the page's live
check, which is cheap by design (stats.views.service_status).

Unlike the rest of the public API these send a wildcard CORS header, so a page
on another site (aiddata.org/geoquery first) can read them from the browser.
They hold only public aggregates, and send no cookies or credentials.
"""
from datetime import datetime, timezone

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from features.models import FeatureCollection
from stats.views import read_snapshot, service_status

from .base import PublicApiBaseMixin
from .serializers import (
    PublicStatsSerializer,
    PublicStatsStatusSerializer,
    PublicStatsTimeseriesSerializer,
)

PERIODS = ("day", "month", "year")
# The snapshot is rebuilt hourly; the status is computed per call
SNAPSHOT_MAX_AGE = 300
STATUS_MAX_AGE = 60


class StatsUnavailable(APIException):
    status_code = 503
    default_detail = "Statistics aren't available yet. Try again later."
    default_code = "stats_unavailable"


class PublicStatsBaseMixin(PublicApiBaseMixin):
    """Public API config plus open CORS and a short browser/CDN cache."""

    max_age = SNAPSHOT_MAX_AGE

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        # Authorization: the public API's (future) Api-Key header
        response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        if response.status_code == 200 and request.method == "GET":
            response["Cache-Control"] = f"public, max-age={self.max_age}"
        return response


def _snapshot() -> dict:
    snapshot = read_snapshot()
    if snapshot is None:
        raise StatsUnavailable()
    return snapshot


def _generated_at(snapshot: dict) -> datetime | None:
    """The snapshot writes "YYYY-MM-DD HH:MM UTC"; the API gives ISO 8601."""
    try:
        return datetime.strptime(snapshot["generated_at"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None


def _series(points) -> list[dict]:
    return [{"date": p["date"], "count": p["count"]} for p in points or []]


class PublicStatsView(PublicStatsBaseMixin, APIView):
    """GET /api/public/v1/stats/ — GeoQuery's headline figures.

    Requests and extracts by state, what's available, how many people and
    organizations have used GeoQuery, recent turnaround, and the most
    requested datasets and boundary sets. Refreshed hourly.
    """

    @extend_schema(responses={200: PublicStatsSerializer, 503: OpenApiTypes.OBJECT})
    def get(self, request):
        s = _snapshot()
        status_counts = s.get("status_counts") or {}
        extract_counts = s.get("extract_counts") or {}

        # The snapshot lists boundary sets by id; the public API names them
        top_sets = s.get("top_boundary_sets") or []
        names = dict(
            FeatureCollection.objects.using("replica")
            .filter(id__in=[b["id"] for b in top_sets], active=True, public=True)
            .values_list("id", "name")
        )

        data = {
            "generated_at": _generated_at(s),
            "requests": {
                "total": s.get("total", 0),
                **{k: status_counts.get(k, 0) for k in ("completed", "pending", "processing", "error")},
                "earlier_versions": s.get("legacy_request_count"),
            },
            "extracts": {
                k: extract_counts.get(k, 0)
                for k in ("total", "completed", "pending", "claimed", "processing", "error")
            },
            "catalog": {
                "datasets": s.get("datasets_available"),
                "boundary_sets": s.get("boundary_sets_available"),
                "boundary_features": s.get("boundary_features_available"),
            },
            "people": {"users": s.get("users"), "organizations": s.get("organizations")},
            "turnaround": s.get("turnaround"),
            "top_datasets": [
                {"name": d["name"], "title": d["title"], "requests": d["requests"]}
                for d in s.get("top_datasets") or []
            ],
            "top_boundary_sets": [
                {"name": names.get(b["id"]), "title": b["title"], "requests": b["requests"]}
                for b in top_sets
            ],
            "cutover": s.get("cutover"),
        }
        return Response(PublicStatsSerializer(data).data)


class PublicStatsTimeseriesView(PublicStatsBaseMixin, APIView):
    """GET /api/public/v1/stats/timeseries/?period=month — the stats page's charts.

    Requests submitted and completed (current GeoQuery and, separately,
    earlier versions) and results extracted, counted per day, month or year.
    Refreshed hourly.
    """

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "period", str, enum=list(PERIODS), default="month", description="Count per day, month or year."
            )
        ],
        responses={200: PublicStatsTimeseriesSerializer, 503: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        period = request.query_params.get("period", "month")
        if period not in PERIODS:
            raise ValidationError({"period": f"must be one of: {', '.join(PERIODS)}"})
        s = _snapshot()

        def by(series, field):
            return _series(((series or {}).get(field) or {}).get(period))

        current, earlier = s.get("time_series"), s.get("legacy_time_series")
        data = {
            "generated_at": _generated_at(s),
            "period": period,
            "cutover": s.get("cutover"),
            "requests_submitted": by(current, "submit_time"),
            "requests_completed": by(current, "complete_time"),
            "earlier_versions_submitted": by(earlier, "submit_time"),
            "earlier_versions_completed": by(earlier, "complete_time"),
            "extracts_completed": _series((s.get("extract_time_series") or {}).get(period)),
        }
        return Response(PublicStatsTimeseriesSerializer(data).data)


class PublicStatsStatusView(PublicStatsBaseMixin, APIView):
    """GET /api/public/v1/stats/status/ — GeoQuery's live status.

    healthy, backlogged or delayed, with the queue behind it. Checked on each
    call. If this can't be reached, show GeoQuery as offline.
    """

    max_age = STATUS_MAX_AGE

    @extend_schema(responses=PublicStatsStatusSerializer)
    def get(self, request):
        return Response(PublicStatsStatusSerializer(service_status()).data)
