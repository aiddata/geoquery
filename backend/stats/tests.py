import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from stats.builder import StatsBuilder


class StatsViewTests(TestCase):
    """The stats page must not query the database on load.

    It serves a snapshot built every 5 minutes by build_stats_report. The page
    previously also polled a live endpoint for queue counts, which ran a GROUP
    BY over ~280M extract_tasks rows -- a global aggregate that no filter can
    prune -- at ~16s and millions of block reads per call. That made the page
    504 as soon as two requests overlapped, and survived two attempted fixes
    because the slow path was the poll, not the page.
    """

    def test_prebuilt_file_is_served_without_touching_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "geoquery_stats.html"
            path.write_text("<html>snapshot</html>", encoding="utf-8")

            with override_settings(STATS_REPORT_PATH=str(path)):
                # Zero queries is the whole point: anything else means the page
                # is doing work per request again.
                with self.assertNumQueries(0):
                    response = self.client.get(reverse("stats"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "<html>snapshot</html>")

    def test_missing_file_falls_back_to_a_live_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-built-yet.html"
            with override_settings(STATS_REPORT_PATH=str(missing)):
                response = self.client.get(reverse("stats"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<html", response.content.lower())

    def test_there_is_no_live_queue_endpoint(self):
        # Regression guard. Reintroducing a per-request queue endpoint puts the
        # 280M-row aggregate back on the page load path.
        with self.assertRaises(NoReverseMatch):
            reverse("stats-workers")
        self.assertEqual(self.client.get("/stats/workers/").status_code, 404)

    def test_page_does_not_fetch_anything_at_runtime(self):
        html = StatsBuilder().render()
        # The path still appears in an explanatory comment; what must not exist
        # is a call to it, or any polling timer.
        self.assertNotIn("fetch('/stats/workers/')", html)
        self.assertNotIn('setInterval(', html)


class StatsBuilderTests(TestCase):
    def test_report_carries_the_queue_counts_the_page_renders(self):
        # The page reads these out of the embedded payload instead of fetching
        # them, so the build is what has to provide them.
        data = StatsBuilder()._collect()

        self.assertIn("extract_counts", data)
        for key in ("completed", "pending", "claimed", "processing", "error", "total"):
            self.assertIn(key, data["extract_counts"])
            self.assertIsInstance(data["extract_counts"][key], int)

        self.assertIn("status_counts", data)
        self.assertIn("generated_at", data)

    def test_rendered_html_exposes_the_counts_to_the_page(self):
        html = StatsBuilder().render()
        self.assertIn("extract_counts", html)
        self.assertIn("q-ext-completed", html)
