import json
import os
import runpy
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from django.contrib.gis.geos import Point
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch, reverse

from analytics.models import ExtractTask, ProcessingOption
from datasets.models import Dataset
from features.models import FeatMap, Feature, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin
from stats.builder import StatsBuilder


class StatsDataViewTests(ReplicaReadsTestMixin, TestCase):
    """The stats endpoint must not query the database on request.

    It serves a snapshot built hourly by default by build_stats_report. The page
    previously polled a live endpoint for queue counts, which ran a GROUP BY
    over ~280M extract_tasks rows -- a global aggregate no filter can prune --
    at ~16s and millions of block reads per call. That made the page 504 as
    soon as two requests overlapped, and survived two attempted fixes because
    the slow path was the poll, not the page. The live-collect fallback reads
    through the "replica" alias.
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


class StatsBuilderTests(ReplicaReadsTestMixin, TestCase):
    # StatsBuilder reads through the "replica" alias.

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

    def test_extract_counts_and_calendar_rollups_share_one_scan_per_dataset(self):
        fc = FeatureCollection.objects.create(name="stats", path="/data/stats")
        fm = FeatMap.objects.create(
            fc=fc, geom=Feature.objects.create(shape=Point(0, 0)), name="stats"
        )
        datasets = [
            Dataset.objects.create(name=f"stats-{i}", path=f"/data/stats-{i}")
            for i in range(2)
        ]  # Inactive/private datasets still count.
        dates = [
            datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 31, tzinfo=timezone.utc),
            datetime(2025, 2, 1, tzinfo=timezone.utc),
        ]
        for dataset in datasets:
            po = ProcessingOption.objects.create(
                dataset=dataset, short_name="mean", function="mean"
            )
            rows = [(1, date) for date in dates] + [
                (1, dates[0]), (1, None), (0, None), (2, None),
                (3, None), (-1, dates[1]), (99, None),
            ]
            for i, (status, complete_time) in enumerate(rows):
                ExtractTask.objects.create(
                    dataset_id=dataset.id, po=po, fm=fm, resource_ids=[i],
                    status=status, complete_time=complete_time,
                )

        with CaptureQueriesContext(connection) as queries:
            data = StatsBuilder().collect()

        self.assertEqual(data["extract_counts"], {
            "completed": 12, "pending": 2, "claimed": 2,
            "processing": 2, "error": 2, "total": 22,
        })
        self.assertEqual(data["extract_time_series"], {
            "day": [
                {"date": "2024-12-31", "count": 4},
                {"date": "2025-01-01", "count": 2},
                {"date": "2025-01-31", "count": 2},
                {"date": "2025-02-01", "count": 2},
            ],
            "month": [
                {"date": "2024-12", "count": 4},
                {"date": "2025-01", "count": 4},
                {"date": "2025-02", "count": 2},
            ],
            "year": [
                {"date": "2024", "count": 4},
                {"date": "2025", "count": 6},
            ],
        })
        scans = [q["sql"] for q in queries if 'FROM "extract_tasks"' in q["sql"]]
        self.assertEqual(len(scans), len(datasets))
        for dataset, sql in zip(datasets, scans):
            self.assertIn(f'"dataset_id" = {dataset.id}', sql)
            self.assertIn("GROUP BY", sql)

    def test_empty_extract_series(self):
        self.assertEqual(
            StatsBuilder().collect()["extract_time_series"],
            {"day": [], "month": [], "year": []},
        )


class StatsScheduleTests(SimpleTestCase):
    def load_settings(self, interval=None):
        env = os.environ.copy()
        env.pop("STATS_REPORT_INTERVAL_SECONDS", None)
        if interval is not None:
            env["STATS_REPORT_INTERVAL_SECONDS"] = str(interval)
        with mock.patch.dict(os.environ, env, clear=True):
            return runpy.run_path(
                str(Path(__file__).resolve().parents[1] / "geoquery" / "settings.py")
            )

    def test_default_is_hourly_and_expires_before_next_tick(self):
        entry = self.load_settings()["CELERY_BEAT_SCHEDULE"]["build-stats-report"]
        self.assertEqual(entry["schedule"], 3600)
        self.assertGreater(entry["options"]["expires"], 0)
        self.assertLess(entry["options"]["expires"], entry["schedule"])

    def test_interval_and_expiry_are_configurable(self):
        for interval in (1, 125, 7200):
            with self.subTest(interval=interval):
                entry = self.load_settings(interval)["CELERY_BEAT_SCHEDULE"]["build-stats-report"]
                self.assertEqual(entry["schedule"], interval)
                self.assertGreater(entry["options"]["expires"], 0)
                self.assertLess(entry["options"]["expires"], interval)

    def test_nonpositive_interval_is_rejected(self):
        for interval in (0, -1):
            with self.subTest(interval=interval):
                with self.assertRaisesMessage(ImproperlyConfigured, "STATS_REPORT_INTERVAL_SECONDS"):
                    self.load_settings(interval)
