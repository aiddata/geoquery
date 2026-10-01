import os
import tempfile
from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase
from prometheus_client import REGISTRY

from analytics import metrics
from analytics.models import ExtractTask, ProcessingOption
from analytics.tasks import processing
from analytics.tasks.processing import _run_extract_task, claim_pending_tasks, run_extract_task
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection

PENDING, DONE, LOCKED, QUEUED, FAILED = 0, 1, 2, 3, -1


def sample(key):
    name, labels = key
    return REGISTRY.get_sample_value(name, dict(labels)) or 0.0


class Delta:
    """Snapshot metric samples so a test can assert on what it added.

    The metrics are process-global and other tests increment them too, so
    absolute values mean nothing here.
    """

    def __init__(self, *keys):
        self.keys = keys
        self.before = {key: sample(key) for key in keys}

    def __getitem__(self, key):
        return sample(key) - self.before[key]


def tasks_total(dataset_id, outcome):
    return ("geoquery_extract_tasks_total", (("dataset_id", str(dataset_id)), ("outcome", outcome)))


def phase_count(phase):
    return ("geoquery_extract_task_phase_seconds_count", (("phase", phase),))


def dispatch_count(stage):
    return ("geoquery_extract_dispatch_seconds_count", (("stage", stage),))


IDLE_COUNT = ("geoquery_extract_slot_idle_seconds_count", ())
PHASES = ("lock", "load", "extract", "write", "finalize")


class TaskMetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        cls.resource = DatasetResource.objects.create(
            dataset=cls.dataset, name="ds-2020", path="2020.tif"
        )
        cls.po = ProcessingOption.objects.create(
            dataset=cls.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        cls.fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))

    _seq = 0

    def make_task(self, *, status=QUEUED):
        type(self)._seq += 1
        return ExtractTask.objects.create(
            resource_ids=[self.resource.id],
            dataset_id=self.dataset.id,
            fm=self.fm,
            po=self.po,
            status=status,
            kwargs={"n": self._seq},
        )

    def run_with(self, task, func, dataset_id=None):
        with mock.patch.object(processing, "get_func", return_value=func):
            return _run_extract_task(task.id, dataset_id)

    def test_a_completed_task_is_counted_once_with_every_phase_timed(self):
        task = self.make_task()
        delta = Delta(tasks_total(self.dataset.id, "completed"), *map(phase_count, PHASES))

        self.run_with(task, lambda g, p, **kw: [("mean", 1.0)], self.dataset.id)

        self.assertEqual(delta[tasks_total(self.dataset.id, "completed")], 1)
        for phase in PHASES:
            self.assertEqual(delta[phase_count(phase)], 1, phase)

    def test_dataset_label_comes_from_the_row_when_the_message_lacks_it(self):
        # Messages from older builds carry bare ids.
        task = self.make_task()
        delta = Delta(tasks_total(self.dataset.id, "completed"), tasks_total("unknown", "completed"))

        self.run_with(task, lambda g, p, **kw: [("mean", 1.0)])

        self.assertEqual(delta[tasks_total(self.dataset.id, "completed")], 1)
        self.assertEqual(delta[tasks_total("unknown", "completed")], 0)

    def test_a_processor_failure_is_counted_as_failed(self):
        task = self.make_task()
        delta = Delta(tasks_total(self.dataset.id, "failed"), phase_count("finalize"))

        def func(g, p, **kw):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.run_with(task, func, self.dataset.id)

        task.refresh_from_db()
        self.assertEqual(task.status, FAILED)
        self.assertEqual(delta[tasks_total(self.dataset.id, "failed")], 1)
        self.assertEqual(delta[phase_count("finalize")], 1)

    def test_an_unclaimable_row_is_counted_as_unavailable_and_only_locks(self):
        task = self.make_task(status=DONE)
        delta = Delta(
            tasks_total(self.dataset.id, "unavailable"), phase_count("lock"), phase_count("load")
        )

        self.assertIsNone(self.run_with(task, lambda g, p, **kw: [], self.dataset.id))

        self.assertEqual(delta[tasks_total(self.dataset.id, "unavailable")], 1)
        self.assertEqual(delta[phase_count("lock")], 1)
        self.assertEqual(delta[phase_count("load")], 0)

    def test_claim_times_the_lock_wait_and_the_hold_separately(self):
        self.make_task(status=PENDING)
        delta = Delta(dispatch_count("lock_wait"), dispatch_count("claim"))

        self.assertEqual(len(claim_pending_tasks(1)), 1)
        # An empty claim still takes and holds the lock, so it is timed too.
        self.assertEqual(claim_pending_tasks(1), [])

        self.assertEqual(delta[dispatch_count("lock_wait")], 2)
        self.assertEqual(delta[dispatch_count("claim")], 2)

    def test_publishing_is_timed_only_when_something_was_claimed(self):
        self.make_task(status=PENDING)
        delta = Delta(dispatch_count("publish"))

        with mock.patch.object(processing.run_extract_task, "delay"):
            processing.dispatch_pending_tasks(limit=1, batch_size=1)
            processing.dispatch_pending_tasks(limit=1, batch_size=1)

        self.assertEqual(delta[dispatch_count("publish")], 1)

    def test_idle_time_is_measured_between_consecutive_batches(self):
        task = self.make_task()
        metrics._last_batch_end = None
        delta = Delta(IDLE_COUNT)

        with mock.patch.object(processing, "dispatch_pending_tasks"), mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", 1.0)]
        ):
            # The first batch a process runs has nothing before it to measure from.
            run_extract_task([[task.id, task.dataset_id]])
            self.assertEqual(delta[IDLE_COUNT], 0)
            run_extract_task([[task.id, task.dataset_id]])

        self.assertEqual(delta[IDLE_COUNT], 1)


class WorkerExporterTests(TestCase):
    def test_disabled_without_a_port_or_a_multiproc_dir(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            metrics, "start_http_server"
        ) as serve:
            with mock.patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": directory}):
                self.assertFalse(metrics.start_worker_exporter(0))
            with mock.patch.dict(os.environ, clear=True):
                self.assertFalse(metrics.start_worker_exporter(9091))
        serve.assert_not_called()

    def test_clears_files_left_by_earlier_processes_but_not_its_own(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            metrics, "start_http_server"
        ) as serve, mock.patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": directory}):
            stale = os.path.join(directory, "counter_999999999.db")
            own = os.path.join(directory, f"counter_{os.getpid()}.db")
            for path in (stale, own):
                open(path, "wb").close()

            self.assertTrue(metrics.start_worker_exporter(9091))

            self.assertFalse(os.path.exists(stale))
            self.assertTrue(os.path.exists(own))
        serve.assert_called_once()
        self.assertEqual(serve.call_args.args, (9091,))
        self.assertEqual(serve.call_args.kwargs["addr"], "0.0.0.0")
