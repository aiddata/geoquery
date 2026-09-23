import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from stats.builder import StatsBuilder


class StatsDataViewTests(TestCase):
    """The stats endpoint must not query the database on request.

    It serves a snapshot built every 5 minutes by build_stats_report. The page
    previously polled a live endpoint for queue counts, which ran a GROUP BY
    over ~280M extract_tasks rows -- a global aggregate no filter can prune --
    at ~16s and millions of block reads per call. That made the page 504 as
    soon as two requests overlapped, and survived two attempted fixes because
    the slow path was the poll, not the page.
    """

    def test_snapshot_is_served_without_touching_the_database(self):
        payload = {"total": 7, "status_counts": {}, "extract_counts": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "geoquery_stats.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with override_settings(STATS_REPORT_PATH=str(path)):
                # Zero queries is the point: anything else means the endpoint
                # is doing work per request again.
                with self.assertNumQueries(0):
                    response = self.client.get(reverse("stats-data"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 7)

    def test_missing_snapshot_falls_back_to_a_live_collect(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(STATS_REPORT_PATH=str(Path(tmp) / "absent.json")):
                response = self.client.get(reverse("stats-data"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("extract_counts", response.json())

    def test_corrupt_snapshot_falls_back_rather_than_erroring(self):
        # A half-written file must not take the page down.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "geoquery_stats.json"
            path.write_text("{not valid json", encoding="utf-8")
            with override_settings(STATS_REPORT_PATH=str(path)):
                response = self.client.get(reverse("stats-data"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("extract_counts", response.json())

    def test_there_is_no_live_queue_endpoint(self):
        # Regression guard. Reintroducing a per-request queue endpoint puts the
        # 280M-row aggregate back on the page load path.
        with self.assertRaises(NoReverseMatch):
            reverse("stats-workers")
        self.assertEqual(self.client.get("/stats/workers/").status_code, 404)

    def test_django_no_longer_claims_the_stats_page_path(self):
        # /stats belongs to the SvelteKit app now. If Django answers it, the
        # app route is shadowed and users get a dead page instead.
        self.assertEqual(self.client.get("/stats/").status_code, 404)


class StatsBuilderTests(TestCase):
    def test_payload_carries_the_queue_counts_the_page_renders(self):
        data = StatsBuilder().collect()

        self.assertIn("extract_counts", data)
        for key in ("completed", "pending", "claimed", "processing", "error", "total"):
            self.assertIn(key, data["extract_counts"])
            self.assertIsInstance(data["extract_counts"][key], int)

        self.assertIn("status_counts", data)
        self.assertIn("generated_at", data)

    def test_build_writes_json_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "geoquery_stats.json"
            status = StatsBuilder(out).build()

            self.assertEqual(status, "Success")
            self.assertIn("extract_counts", json.loads(out.read_text()))
            # the temp file used for the atomic replace must not survive
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])
