from datetime import timedelta
from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from analytics.management.commands.free_stale_processing_tasks import _free_stale_tasks
from analytics.management.commands.run_processing_tasks import _run_processing_tasks
from analytics.models import ExtractTask, ProcessingOption
from analytics.tasks import maintenance, processing
from analytics.tasks.processing import claim_pending_tasks, run_extract_task
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection

PENDING, DONE, LOCKED, QUEUED, FAILED = 0, 1, 2, 3, -1


class DispatchTestCase(TestCase):
    """Claiming, chaining, and reaping of extract tasks.

    Real contention (two transactions claiming at once, which is what FOR
    UPDATE SKIP LOCKED exists for) needs two connections and cannot run inside
    TestCase's single wrapping transaction; these cover the sequential
    contract that the concurrent one builds on.
    """

    @classmethod
    def setUpTestData(cls):
        dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        cls.resource = DatasetResource.objects.create(
            dataset=dataset, name="ds-2020", path="2020.tif"
        )
        cls.po = ProcessingOption.objects.create(
            dataset=dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        cls.fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))

    _seq = 0

    def make_task(self, *, status=PENDING, priority=0, age=None):
        """Create a task. Distinct kwargs keep the (resource, fm, po, kwargs) unique index happy."""
        type(self)._seq += 1
        task = ExtractTask.objects.create(
            resource=self.resource,
            fm=self.fm,
            po=self.po,
            status=status,
            priority=priority,
            kwargs={"n": self._seq},
        )
        if age is not None:
            # submit_time is auto_now_add, so backdate after the fact.
            ExtractTask.objects.filter(id=task.id).update(
                submit_time=timezone.now() - age, update_time=timezone.now() - age
            )
        return task

    def statuses(self, *tasks):
        return [ExtractTask.objects.get(id=t.id).status for t in tasks]

    # --- claim_pending_tasks -------------------------------------------------

    def test_claim_orders_by_priority_then_age_and_marks_queued(self):
        old = self.make_task(age=timedelta(hours=2))
        urgent = self.make_task(priority=1, age=timedelta(minutes=1))
        new = self.make_task()

        self.assertEqual(claim_pending_tasks(2), [urgent.id, old.id])
        self.assertEqual(self.statuses(urgent, old, new), [QUEUED, QUEUED, PENDING])

    def test_successive_claims_are_disjoint(self):
        a, b, c = self.make_task(), self.make_task(), self.make_task()

        first = claim_pending_tasks(2)
        second = claim_pending_tasks(2)

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 1)
        self.assertEqual(set(first) | set(second), {a.id, b.id, c.id})
        self.assertEqual(claim_pending_tasks(2), [])

    def test_claim_ignores_non_pending_rows(self):
        for status in (DONE, LOCKED, QUEUED, FAILED):
            self.make_task(status=status)
        self.assertEqual(claim_pending_tasks(10), [])

    # --- run_extract_task ----------------------------------------------------

    def run_task(self, task, func):
        """Run the task synchronously with the processor and broker stubbed."""
        with (
            mock.patch.object(processing, "get_func", return_value=func),
            mock.patch.object(run_extract_task, "delay") as delay,
        ):
            result = run_extract_task(task.id)
        return result, delay

    def test_queued_row_is_run_and_chains_to_next_pending(self):
        first = self.make_task(status=QUEUED)
        second = self.make_task()

        result, delay = self.run_task(first, lambda geometry, path, **kw: [("mean", 1.5)])

        self.assertEqual(result, {"task_id": first.id, "results": 1})
        self.assertEqual(self.statuses(first, second), [DONE, QUEUED])
        delay.assert_called_once_with(second.id)

    def test_noop_still_chains(self):
        # The row was already finished by the time its message arrived; the
        # chain must carry on regardless or every collision kills a worker.
        stale = self.make_task(status=DONE)
        pending = self.make_task()

        result, delay = self.run_task(stale, mock.Mock())

        self.assertIsNone(result)
        self.assertEqual(self.statuses(stale, pending), [DONE, QUEUED])
        delay.assert_called_once_with(pending.id)

    def test_failure_marks_task_and_still_chains(self):
        def broken(geometry, path, **kw):
            raise RuntimeError("boom")

        first = self.make_task(status=QUEUED)
        second = self.make_task()

        with self.assertRaises(RuntimeError):
            self.run_task(first, broken)

        failed = ExtractTask.objects.get(id=first.id)
        self.assertEqual(failed.status, FAILED)
        self.assertIn("boom", failed.error)
        self.assertEqual(self.statuses(second), [QUEUED])

    def test_dispatch_failure_does_not_mask_task_outcome(self):
        first = self.make_task(status=QUEUED)
        self.make_task()

        with (
            mock.patch.object(processing, "get_func", return_value=lambda g, p, **kw: []),
            mock.patch.object(run_extract_task, "delay", side_effect=OSError("broker down")),
        ):
            result = run_extract_task(first.id)

        self.assertEqual(result, {"task_id": first.id, "results": 0})
        self.assertEqual(self.statuses(first), [DONE])

    def test_no_chain_when_nothing_pending(self):
        only = self.make_task(status=QUEUED)
        _, delay = self.run_task(only, lambda g, p, **kw: [])
        delay.assert_not_called()

    # --- _run_processing_tasks ------------------------------------------------

    def test_batch_dispatch_claims_then_moves_on(self):
        tasks = [self.make_task() for _ in range(3)]

        with mock.patch.object(run_extract_task, "delay") as delay:
            first = _run_processing_tasks(limit=2)
            second = _run_processing_tasks(limit=2)
            third = _run_processing_tasks(limit=2)

        self.assertEqual((first["dispatched"], second["dispatched"], third["dispatched"]), (2, 1, 0))
        self.assertEqual(delay.call_count, 3)
        self.assertEqual(self.statuses(*tasks), [QUEUED] * 3)

    def test_dry_run_claims_nothing(self):
        tasks = [self.make_task() for _ in range(3)]

        with mock.patch.object(run_extract_task, "delay") as delay:
            result = _run_processing_tasks(limit=2, dry_run=True)

        self.assertEqual(result, {"dispatched": 2, "dry_run": True})
        delay.assert_not_called()
        self.assertEqual(self.statuses(*tasks), [PENDING] * 3)

    # --- _free_stale_tasks ------------------------------------------------------

    def test_reaper_frees_stale_locked_and_queued_only(self):
        stale_locked = self.make_task(status=LOCKED, age=timedelta(hours=1))
        stale_queued = self.make_task(status=QUEUED, age=timedelta(hours=1))
        fresh_queued = self.make_task(status=QUEUED, age=timedelta(minutes=1))
        stale_done = self.make_task(status=DONE, age=timedelta(hours=1))

        self.assertEqual(_free_stale_tasks(30), 2)
        self.assertEqual(
            self.statuses(stale_locked, stale_queued, fresh_queued, stale_done),
            [PENDING, PENDING, QUEUED, DONE],
        )


class BeatDispatchTests(TestCase):
    """dispatch_processing_tasks sizes its top-up from processing workers only."""

    PROC, BG = "celery@processing-worker-a", "celery@background-worker-b"
    TASK = "analytics.tasks.processing.run_extract_task"

    def run_beat(self, active_queues, stats, active, reserved):
        inspector = mock.Mock(
            active_queues=mock.Mock(return_value=active_queues),
            stats=mock.Mock(return_value=stats),
            active=mock.Mock(return_value=active),
            reserved=mock.Mock(return_value=reserved),
        )
        with (
            mock.patch("celery.current_app.control.inspect", return_value=inspector) as inspect,
            mock.patch(
                "analytics.management.commands.run_processing_tasks._run_processing_tasks",
                return_value={"dispatched": 0, "dry_run": False},
            ) as run,
        ):
            result = maintenance.dispatch_processing_tasks()
        return result, inspect, run

    def test_counts_slots_and_in_flight_from_processing_workers_only(self):
        # Replies from the background worker are present in every payload and
        # must not contribute to either side of the slot arithmetic.
        result, inspect, run = self.run_beat(
            active_queues={self.PROC: [{"name": "processing"}], self.BG: [{"name": "background"}]},
            stats={self.PROC: {"pool": {"max-concurrency": 16}}, self.BG: {"pool": {"max-concurrency": 4}}},
            active={self.PROC: [{"name": self.TASK}] * 2, self.BG: [{"name": self.TASK}]},
            reserved={self.PROC: [{"name": self.TASK}, {"name": "other.task"}], self.BG: []},
        )

        inspect.assert_any_call(destination=[self.PROC], timeout=5.0)
        run.assert_called_once_with(limit=13)

    def test_full_workers_dispatch_nothing(self):
        result, _, run = self.run_beat(
            active_queues={self.PROC: [{"name": "processing"}]},
            stats={self.PROC: {"pool": {"max-concurrency": 2}}},
            active={self.PROC: [{"name": self.TASK}] * 2},
            reserved={},
        )
        run.assert_not_called()
        self.assertEqual(result, {"dispatched": 0, "total_slots": 2, "in_flight": 2})

    def test_no_processing_workers_dispatches_nothing(self):
        result, _, run = self.run_beat(
            active_queues={self.BG: [{"name": "background"}]},
            stats={self.BG: {"pool": {"max-concurrency": 4}}},
            active={},
            reserved={},
        )
        run.assert_not_called()
        self.assertEqual(result["dispatched"], 0)
