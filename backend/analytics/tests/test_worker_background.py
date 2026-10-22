"""The worker slot's background path: coverage chunk, then a lease page."""

import threading
from unittest import mock

from django.contrib.gis.geos import Polygon
from django.db import OperationalError, connections
from django.test import TestCase

from analytics import extract_worker
from analytics.models import Coverage, ExtractTask
from analytics.tasks import leases
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs


class BackgroundSlotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset, _, _ = make_dataset(
            "slot", is_global=False, extent=Polygon(((0, 0), (9, 0), (9, 9), (0, 9), (0, 0))))
        cls.fc, cls.fms = make_collection("slot-fc", 3)
        settle_inputs()

    def setUp(self):
        self.stop = threading.Event()
        self.wait = mock.patch.object(self.stop, "wait").start()
        mock.patch.object(extract_worker, "_stop", self.stop).start()
        mock.patch.object(connections, "close_all").start()
        mock.patch.object(leases, "get_func", return_value=lambda g, p, **kw: [("v", 1.0)]).start()
        mock.patch.object(leases, "get_batch_func", return_value=None).start()
        extract_worker._infra_failures = 0
        self.addCleanup(mock.patch.stopall)

    def test_with_no_pending_tasks_a_slot_covers_then_leases(self):
        # One unit of work: a coverage chunk lifts the pair's cap, and the
        # lease that follows in the same unit takes the covered features.
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(extract_worker.run_chunk(60), 0)
        self.assertEqual(Coverage.objects.filter(dataset=self.dataset, status=1).count(), 3)
        self.assertEqual(ExtractTask.objects.filter(dataset_id=self.dataset.id, status=1).count(), 3)
        self.wait.assert_not_called()
        # Nothing left: the slot idles.
        extract_worker.run_chunk(60)
        [(seconds,), _] = self.wait.call_args
        self.assertGreaterEqual(seconds, 45)

    def test_a_running_lease_is_visible_to_the_slot_metrics(self):
        seen = []
        starts = [0.0]

        def record(lease, stop):
            seen.append(starts[0])
            return "completed"

        with mock.patch.object(extract_worker, "_chunk_starts", starts), \
                mock.patch("analytics.tasks.leases.run_lease", side_effect=record):
            extract_worker.run_chunk(60)
        self.assertTrue(seen and seen[0] > 0)
        self.assertEqual(starts[0], 0)

    def test_database_failures_back_off_exponentially_and_reset_on_success(self):
        with mock.patch("analytics.coverage.run_coverage_chunk", side_effect=OperationalError("down")), \
                self.assertLogs("analytics.extract_worker", "ERROR"):
            extract_worker.run_chunk(60)
            extract_worker.run_chunk(60)
            extract_worker.run_chunk(60)
        delays = [call.args[0] for call in self.wait.call_args_list]
        self.assertEqual(len(delays), 3)
        self.assertTrue(3.5 <= delays[0] <= 6.5 and 7 <= delays[1] <= 13 and 14 <= delays[2] <= 26, delays)
        extract_worker.run_chunk(60)
        self.assertEqual(extract_worker._infra_failures, 0)

    def test_a_stopping_slot_starts_no_background_work(self):
        self.stop.set()
        with mock.patch("analytics.coverage.run_coverage_chunk") as cover:
            extract_worker.run_chunk(60)
        cover.assert_not_called()
