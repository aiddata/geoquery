"""Public stats endpoints (GEO-98): the /stats page's figures, in a stable shape."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from analytics.models import Request
from features.models import FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin

POINTS = {
    "day": [{"date": "2026-11-01", "count": 3}, {"date": "2026-11-02", "count": 4}],
    "month": [{"date": "2026-11", "count": 7}],
    "year": [{"date": "2026", "count": 7}],
}
LEGACY_POINTS = {"day": [], "month": [{"date": "2019-05", "count": 2}], "year": [{"date": "2019", "count": 2}]}

# A snapshot as stats.builder writes it
SNAPSHOT = {
    "total": 120,
    "datasets_available": 63,
    "boundary_sets_available": 900,
    "boundary_features_available": 250000,
    "turnaround": {"days": 30, "count": 40, "median_seconds": 600.0, "p90_seconds": 3600.0},
    "users": 5000,
    "organizations": 1200,
    "top_datasets": [{"name": "viirs", "title": "VIIRS Nighttime Lights", "requests": 50}],
    "top_boundary_sets": [],  # filled in setUp, with real ids
    "status_counts": {"completed": 100, "pending": 5, "processing": 10, "error": 5},
    "extract_counts": {"completed": 900, "pending": 50, "claimed": 5, "processing": 20, "error": 25, "total": 1000},
    "time_series": {"submit_time": POINTS, "complete_time": POINTS},
    "extract_time_series": POINTS,
    "legacy_request_count": 30000,
    "legacy_time_series": {"submit_time": LEGACY_POINTS, "complete_time": LEGACY_POINTS},
    "cutover": "2026-08-18",
    "generated_at": "2026-11-19 21:00 UTC",
}


class PublicStatsTestCase(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "geoquery_stats.json"
        self.settings = override_settings(
            STATS_REPORT_PATH=str(self.path), STATUS_BACKLOG_MINUTES=60,
            STATS_REPORT_INTERVAL_SECONDS=3600, STATS_REPORT_ENABLED=True,
        )
        self.settings.enable()

    def tearDown(self):
        self.settings.disable()
        self.tmp.cleanup()

    def write(self, snapshot):
        self.path.write_text(json.dumps(snapshot), encoding="utf-8")


class PublicStatsSummaryTests(PublicStatsTestCase):
    def setUp(self):
        super().setUp()
        ghana = FeatureCollection.objects.create(
            active=True, public=True, name="gha_adm2", path="gha_adm2", title="Ghana ADM2"
        )
        hidden = FeatureCollection.objects.create(
            active=True, public=False, name="private_set", path="private_set", title="Private"
        )
        self.snapshot = {
            **SNAPSHOT,
            "top_boundary_sets": [
                {"id": ghana.id, "title": "Ghana ADM2", "requests": 20},
                {"id": hidden.id, "title": "Was public", "requests": 3},
            ],
        }
        self.write(self.snapshot)

    def get(self):
        response = self.client.get(reverse("public_api:stats"))
        self.assertEqual(response.status_code, 200)
        return response

    def test_covers_every_figure_on_the_stats_page(self):
        body = self.get().json()
        self.assertEqual(body["generated_at"], "2026-11-19T21:00:00Z")
        self.assertEqual(
            body["requests"],
            {"total": 120, "completed": 100, "pending": 5, "processing": 10, "error": 5, "earlier_versions": 30000},
        )
        self.assertEqual(
            body["extracts"],
            {"total": 1000, "completed": 900, "pending": 50, "claimed": 5, "processing": 20, "error": 25},
        )
        self.assertEqual(body["catalog"], {"datasets": 63, "boundary_sets": 900, "boundary_features": 250000})
        self.assertEqual(body["people"], {"users": 5000, "organizations": 1200})
        self.assertEqual(body["turnaround"], SNAPSHOT["turnaround"])
        self.assertEqual(body["top_datasets"], [{"name": "viirs", "title": "VIIRS Nighttime Lights", "requests": 50}])
        self.assertEqual(body["cutover"], "2026-08-18")

    def test_boundary_sets_are_named_as_elsewhere_in_the_api(self):
        top = self.get().json()["top_boundary_sets"]
        self.assertEqual(top[0], {"name": "gha_adm2", "title": "Ghana ADM2", "requests": 20})
        # Made private since the snapshot was built: no name to look it up by
        self.assertIsNone(top[1]["name"])

    def test_leaves_out_internal_fields(self):
        body = self.get().json()
        self.assertEqual(
            set(body),
            {"generated_at", "requests", "extracts", "catalog", "people", "turnaround",
             "top_datasets", "top_boundary_sets", "cutover"},
        )

    def test_an_older_snapshot_gives_nulls_for_what_it_lacks(self):
        old = {k: SNAPSHOT[k] for k in ("total", "status_counts", "extract_counts", "time_series",
                                         "extract_time_series", "generated_at")}
        self.write(old)
        body = self.get().json()
        self.assertEqual(body["catalog"], {"datasets": None, "boundary_sets": None, "boundary_features": None})
        self.assertIsNone(body["requests"]["earlier_versions"])
        self.assertIsNone(body["turnaround"])
        self.assertEqual(body["top_datasets"], [])

    def test_open_to_other_sites_and_cacheable(self):
        response = self.client.get(reverse("public_api:stats"), HTTP_ORIGIN="https://www.aiddata.org")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertNotIn("Access-Control-Allow-Credentials", response)
        self.assertEqual(response["Cache-Control"], "public, max-age=300")

    def test_a_preflight_from_another_site_is_answered(self):
        # corsheaders would answer this itself, without the header, for an
        # origin outside its allowlist; these paths are excluded from it
        response = self.client.options(
            reverse("public_api:stats"),
            HTTP_ORIGIN="https://www.aiddata.org",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization",
        )
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("Authorization", response["Access-Control-Allow-Headers"])

    def test_no_snapshot_yet_is_unavailable_not_a_live_build(self):
        self.path.unlink()
        with mock.patch("stats.builder.StatsBuilder.collect") as collect:
            response = self.client.get(reverse("public_api:stats"))
        collect.assert_not_called()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], 503)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertNotIn("Cache-Control", response)


class PublicStatsTimeseriesTests(PublicStatsTestCase):
    def setUp(self):
        super().setUp()
        self.write(SNAPSHOT)

    def get(self, **params):
        return self.client.get(reverse("public_api:stats-timeseries"), params)

    def test_monthly_by_default(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["period"], "month")
        self.assertEqual(body["generated_at"], "2026-11-19T21:00:00Z")
        self.assertEqual(body["cutover"], "2026-08-18")
        self.assertEqual(body["requests_submitted"], POINTS["month"])
        self.assertEqual(body["requests_completed"], POINTS["month"])
        self.assertEqual(body["earlier_versions_submitted"], LEGACY_POINTS["month"])
        self.assertEqual(body["earlier_versions_completed"], LEGACY_POINTS["month"])
        self.assertEqual(body["extracts_completed"], POINTS["month"])

    def test_by_day_or_year(self):
        self.assertEqual(self.get(period="day").json()["requests_submitted"], POINTS["day"])
        self.assertEqual(self.get(period="year").json()["extracts_completed"], POINTS["year"])

    def test_rejects_an_unknown_period(self):
        response = self.get(period="week")
        self.assertEqual(response.status_code, 400)
        self.assertIn("period", response.json()["error"]["message"])

    def test_an_older_snapshot_without_earlier_versions(self):
        self.write({k: v for k, v in SNAPSHOT.items() if k != "legacy_time_series"})
        body = self.get().json()
        self.assertEqual(body["earlier_versions_submitted"], [])
        self.assertEqual(body["requests_submitted"], POINTS["month"])


class PublicStatsStatusTests(PublicStatsTestCase):
    def setUp(self):
        super().setUp()
        self.write({})

    def test_live_status_as_the_stats_page_shows_it(self):
        Request.objects.create(contact="a@b.c", status=-1)
        response = self.client.get(reverse("public_api:stats-status"), HTTP_ORIGIN="https://aiddata.org")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "healthy")
        self.assertEqual(body["unfinished_requests"], 1)
        self.assertEqual(body["backlog_after_seconds"], 3600)
        self.assertEqual(
            set(body),
            {"state", "unfinished_requests", "oldest_wait_seconds", "backlog_after_seconds",
             "snapshot_age_seconds", "checked_at"},
        )
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertEqual(response["Cache-Control"], "public, max-age=60")
