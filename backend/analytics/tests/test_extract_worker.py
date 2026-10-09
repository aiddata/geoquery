import threading
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from unittest import mock

from django.contrib.gis.geos import Point
from django.db import OperationalError, connection, connections
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from analytics import extract_worker, metrics
from analytics.models import ExtractData, ExtractTask, ProcessingOption
from analytics.tasks import processing
from analytics.tests.test_metrics import Delta, tasks_total
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection

PENDING, DONE, LOCKED, QUEUED, FAILED = 0, 1, 2, 3, -1

CHUNK_COUNT = ("geoquery_extract_chunk_seconds_count", ())
IDLE_COUNT = ("geoquery_extract_slot_idle_seconds_count", ())
BREAKS = ("geoquery_extract_worker_pool_breaks_total", ())


@override_settings(EXTRACT_TASK_CLAIM_BATCH=10)
class RunChunkTests(TestCase):
    """run_chunk, in-process: what one worker slot does with one claim.

    Spawned children would connect to the real database name rather than the
    test database, so the process pool itself is covered by ExtractWorkerTests
    with a fake executor instead.
    """

    @classmethod
    def setUpTestData(cls):
        dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        cls.resource = DatasetResource.objects.create(
            dataset=dataset, name="ds-2020", path="2020.tif"
        )
        cls.po = ProcessingOption.objects.create(
            dataset=dataset, short_name="mean", function="rasterstats_default_mean",
            active=True,
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        cls.fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))

    _seq = 0

    def make_tasks(self, n):
        tasks = []
        for _ in range(n):
            type(self)._seq += 1
            tasks.append(ExtractTask.objects.create(
                resource_ids=[self.resource.id],
                dataset_id=self.resource.dataset_id,
                fm=self.fm,
                po=self.po,
                kwargs={"n": self._seq},
            ))
        return tasks

    def statuses(self, tasks):
        return [ExtractTask.objects.get(id=t.id).status for t in tasks]

    def setUp(self):
        self.stop = threading.Event()
        self.wait = mock.patch.object(self.stop, "wait").start()
        mock.patch.object(extract_worker, "_stop", self.stop).start()
        # Closing the connection would end TestCase's wrapping transaction.
        self.close_all = mock.patch.object(connections, "close_all").start()
        self.addCleanup(mock.patch.stopall)

    def run_chunk(self, processor=lambda g, p, **kw: [("mean", 1.0)]):
        with mock.patch.object(processing, "get_func", return_value=processor):
            return extract_worker.run_chunk(60)

    def test_runs_every_claimed_task(self):
        tasks = self.make_tasks(3)

        self.assertEqual(self.run_chunk(), 3)

        self.assertEqual(self.statuses(tasks), [DONE] * 3)
        self.wait.assert_not_called()
        self.close_all.assert_called_once()

    def test_metadata_reads_are_bounded_batches_without_task_rereads(self):
        tasks = self.make_tasks(5)
        with (
            mock.patch.object(processing, "INPUT_BATCH_SIZE", 2),
            mock.patch.object(processing, "load_input_batch", wraps=processing.load_input_batch) as load,
            CaptureQueriesContext(connection) as queries,
        ):
            self.assertEqual(self.run_chunk(), 5)
        self.assertEqual([len(call.args[0]) for call in load.call_args_list], [2, 2, 1])
        reads = [q["sql"] for q in queries if "SELECT" in q["sql"] and "FROM extract_tasks" in q["sql"]]
        self.assertEqual(len(reads), 1, reads)  # The chunk claim only.
        self.assertEqual(self.statuses(tasks), [DONE] * 5)

    def test_metadata_batch_failure_flushes_work_and_releases_remainder(self):
        tasks = self.make_tasks(5)
        fetch = processing.load_input_batch
        calls = 0

        def fail_second_batch(claims):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OperationalError("metadata unavailable on both databases")
            return fetch(claims)

        with (
            mock.patch.object(processing, "INPUT_BATCH_SIZE", 2),
            mock.patch.object(processing, "load_input_batch", side_effect=fail_second_batch),
            self.assertLogs("analytics.extract_worker", "ERROR"),
        ):
            self.run_chunk()
        self.assertEqual(self.statuses(tasks), [DONE, DONE, PENDING, PENDING, PENDING])
        self.wait.assert_called_once()

    def test_missing_resource_fails_task_and_other_tasks_complete(self):
        tasks = self.make_tasks(3)
        missing = DatasetResource.objects.create(
            dataset_id=self.resource.dataset_id, name="deleted", path="deleted.tif",
        )
        resource_id = missing.id
        ExtractTask.objects.filter(dataset_id=tasks[1].dataset_id, id=tasks[1].id).update(
            resource_ids=[resource_id],
        )
        missing.delete()

        with self.assertLogs(level="ERROR"):
            self.assertEqual(self.run_chunk(), 3)

        self.assertEqual(self.statuses(tasks), [DONE, FAILED, DONE])
        failed = ExtractTask.objects.get(dataset_id=tasks[1].dataset_id, id=tasks[1].id)
        self.assertEqual(failed.error, repr(KeyError(resource_id)))
        self.assertEqual(
            set(ExtractData.objects.filter(dataset_id=self.resource.dataset_id)
                .values_list("extract_task_id", flat=True)),
            {tasks[0].id, tasks[2].id},
        )
        self.wait.assert_not_called()

    def test_results_are_buffered_and_written_in_one_batch(self):
        tasks = self.make_tasks(3)
        completed = tasks_total(self.resource.dataset_id, "completed")
        delta = Delta(completed)

        def compute(geometry, path, **kw):
            self.assertEqual(self.statuses(tasks), [LOCKED] * 3)
            self.assertFalse(ExtractData.objects.filter(dataset_id=self.resource.dataset_id).exists())
            self.assertEqual(delta[completed], 0)
            return [("mean", 1.0)]

        with self.captureOnCommitCallbacks(execute=True), CaptureQueriesContext(connection) as queries:
            self.run_chunk(compute)
            self.assertEqual(delta[completed], 0)  # outer test transaction not committed

        copies = [q for q in queries if q["sql"].startswith("COPY extract_data")]
        finalizes = [q for q in queries if "UPDATE extract_tasks AS t\n" in q["sql"] and "SET status = v.status" in q["sql"]]
        self.assertEqual(len(copies), 1)
        self.assertEqual(len(finalizes), 1)
        self.assertEqual(ExtractData.objects.filter(dataset_id=self.resource.dataset_id).count(), 3)
        self.assertEqual(delta[completed], 3)
        self.assertEqual(self.statuses(tasks), [DONE] * 3)

    def test_transient_flush_failure_retries_without_recomputing(self):
        retries = ("geoquery_extract_flush_retries_total", ())
        delta = Delta(retries)
        tasks = self.make_tasks(3)
        processor = mock.Mock(return_value=[("mean", 1.0)])
        persist = processing._persist_outcomes
        attempts = []

        def fail_once(outcomes):
            attempts.append(outcomes)
            if len(attempts) == 1:
                raise OperationalError("connection lost")
            return persist(outcomes)

        with mock.patch.object(processing, "_persist_outcomes", side_effect=fail_once), \
                mock.patch.object(processing.time, "sleep"), \
                self.assertLogs("analytics.tasks.processing", "WARNING"):
            self.run_chunk(processor)
        self.assertEqual(processor.call_count, 3)
        self.assertEqual(len(attempts), 2)
        self.assertIs(attempts[0], attempts[1])
        self.assertEqual(self.statuses(tasks), [DONE] * 3)
        self.assertEqual(delta[retries], 1)

    def test_exhausted_flush_retries_release_tasks_without_counting_completion(self):
        tasks = self.make_tasks(3)
        completed = tasks_total(self.resource.dataset_id, "completed")
        retries = ("geoquery_extract_flush_retries_total", ())
        failures = ("geoquery_extract_flush_failures_total", ())
        delta = Delta(completed, retries, failures)
        with mock.patch.object(processing, "_persist_outcomes", side_effect=OperationalError("offline")) as persist, \
                mock.patch.object(processing.time, "sleep"), self.assertLogs(level="WARNING"):
            self.run_chunk()
        self.assertEqual(persist.call_count, 3)
        self.assertEqual(self.statuses(tasks), [PENDING] * 3)
        self.assertEqual(delta[completed], 0)
        self.wait.assert_called_once()
        self.assertEqual(delta[retries], 2)
        self.assertEqual(delta[failures], 1)

    def test_active_chunk_is_visible_during_work_and_cleared_after_flush(self):
        self.make_tasks(1)
        starts = [0.0]

        def compute(*args, **kwargs):
            self.assertGreater(starts[0], 0)
            return [("mean", 1.0)]

        with mock.patch.object(extract_worker, "_chunk_starts", starts):
            self.run_chunk(compute)
        self.assertEqual(starts, [0])

    def test_invalid_result_isolated_and_previous_results_preserved(self):
        tasks = self.make_tasks(3)
        completed = tasks_total(self.resource.dataset_id, "completed")
        failed = tasks_total(self.resource.dataset_id, "failed")
        delta = Delta(completed, failed)
        ExtractData.objects.create(
            dataset_id=tasks[1].dataset_id, extract_task_id=tasks[1].id,
            name="mean", float_value=9.0,
        )
        calls = 0

        def compute(geometry, path, **kw):
            nonlocal calls
            calls += 1
            return [("mean", "x" * 101 if calls == 2 else 1.0)]

        with self.captureOnCommitCallbacks(execute=True), self.assertLogs(level="ERROR"):
            self.run_chunk(compute)
        self.assertEqual(calls, 3)
        self.assertEqual(self.statuses(tasks), [DONE, FAILED, DONE])
        self.assertEqual(delta[completed], 2)
        self.assertEqual(delta[failed], 1)
        self.assertEqual(ExtractData.objects.get(
            dataset_id=tasks[1].dataset_id, extract_task_id=tasks[1].id, name="mean",
        ).float_value, 9.0)

    def test_reclaimed_task_is_not_overwritten_by_buffered_results(self):
        tasks = self.make_tasks(2)
        calls = 0

        def compute(geometry, path, **kw):
            nonlocal calls
            calls += 1
            if calls == 2:
                # Simulate a reaper and another claim after the first task
                # was computed. Status alone cannot detect this case.
                ExtractTask.objects.filter(
                    dataset_id=tasks[0].dataset_id, id=tasks[0].id,
                ).update(update_time=timezone.now())
                ExtractData.objects.create(
                    dataset_id=tasks[0].dataset_id, extract_task_id=tasks[0].id,
                    name="mean", float_value=9.0,
                )
            return [("mean", 1.0)]

        self.run_chunk(compute)
        self.assertEqual(self.statuses(tasks), [LOCKED, DONE])
        self.assertEqual(ExtractData.objects.get(
            dataset_id=tasks[0].dataset_id, extract_task_id=tasks[0].id, name="mean",
        ).float_value, 9.0)

    def test_a_failing_task_does_not_stop_the_chunk(self):
        tasks = self.make_tasks(3)
        calls = []

        def first_fails(geometry, path, **kw):
            calls.append(path)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return [("mean", 1.0)]

        with self.assertLogs("analytics.extract_worker", "ERROR"):
            self.assertEqual(self.run_chunk(first_fails), 3)

        self.assertEqual(self.statuses(tasks), [FAILED, DONE, DONE])
        self.wait.assert_not_called()

    def test_an_empty_queue_waits_before_the_next_claim(self):
        self.assertEqual(self.run_chunk(), 0)

        [(seconds,), _] = self.wait.call_args
        self.assertGreaterEqual(seconds, 60 * 0.75)
        self.assertLessEqual(seconds, 60 * 1.25)
        self.close_all.assert_called_once()

    def test_stopping_mid_chunk_releases_the_unstarted_tasks(self):
        tasks = self.make_tasks(3)

        def stop_after_first(geometry, path, **kw):
            self.stop.set()
            return [("mean", 1.0)]

        self.assertEqual(self.run_chunk(stop_after_first), 3)

        self.assertEqual(self.statuses(tasks), [DONE, PENDING, PENDING])
        self.assertEqual(ExtractData.objects.get(
            dataset_id=tasks[0].dataset_id, extract_task_id=tasks[0].id, name="mean",
        ).float_value, 1.0)

    def test_a_failed_claim_backs_off(self):
        with mock.patch.object(
            processing, "claim_pending_tasks", side_effect=RuntimeError("db down")
        ), self.assertLogs("analytics.extract_worker", "ERROR"):
            self.assertEqual(self.run_chunk(), 0)

        self.wait.assert_called_once()
        self.close_all.assert_called_once()

    def test_a_chunk_failure_releases_what_it_had_not_started(self):
        tasks = self.make_tasks(3)

        with mock.patch.object(
            processing, "_run_extract_task", side_effect=[None, KeyboardInterrupt]
        ), self.assertRaises(KeyboardInterrupt):
            self.run_chunk()

        # Started tasks stay running -- the second may have written half its
        # results -- and are left to the reaper. Only the one never reached
        # goes back to the queue.
        self.assertEqual(self.statuses(tasks), [LOCKED, LOCKED, PENDING])

    def test_chunks_are_timed_only_when_they_claimed_something(self):
        delta = Delta(CHUNK_COUNT)
        self.run_chunk()
        self.assertEqual(delta[CHUNK_COUNT], 0)

        self.make_tasks(1)
        self.run_chunk()
        self.assertEqual(delta[CHUNK_COUNT], 1)

    def test_idle_time_is_measured_between_consecutive_chunks(self):
        metrics._last_batch_end = None
        delta = Delta(IDLE_COUNT)

        # The first chunk a process runs has nothing before it to measure from.
        self.run_chunk()
        self.assertEqual(delta[IDLE_COUNT], 0)
        self.run_chunk()

        self.assertEqual(delta[IDLE_COUNT], 1)


class FakeSlot:
    """Stands in for one slot's ProcessPoolExecutor; chunks resolve at once."""

    def __init__(self, worker, script):
        self.worker = worker
        self.script = script
        self.shutdowns = []
        self.broken = False

    def submit(self, fn, *args):
        if self.broken:
            raise BrokenProcessPool("A child process terminated abruptly")
        self.script.submissions += 1
        future = Future()
        outcome = self.script.outcomes.pop(0) if self.script.outcomes else 1
        if isinstance(outcome, BaseException):
            future.set_exception(outcome)
        else:
            future.set_result(outcome)
        if self.script.submissions in self.script.dies_after:
            # The chunk returned; its process dies before the next submit.
            self.broken = True
        if self.script.submissions >= self.script.stop_after:
            self.worker.stop()
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdowns.append((wait, cancel_futures))


class Script:
    def __init__(self, stop_after, outcomes=(), dies_after=()):
        self.stop_after = stop_after
        self.outcomes = list(outcomes)
        self.dies_after = set(dies_after)
        self.submissions = 0


class ExtractWorkerTests(SimpleTestCase):
    def make_worker(self, concurrency, script):
        slots = []

        def factory():
            slots.append(FakeSlot(worker, script))
            return slots[-1]

        worker = extract_worker.ExtractWorker(
            concurrency=concurrency, max_chunks_per_child=1, idle_seconds=0,
            executor_factory=factory,
        )
        return worker, slots

    def test_slots_are_resubmitted_until_stopped(self):
        script = Script(stop_after=5)
        worker, slots = self.make_worker(2, script)

        worker.run()

        self.assertEqual(script.submissions, 5)
        self.assertEqual(len(slots), 2)
        for slot in slots:
            self.assertEqual(slot.shutdowns, [(True, False)])

    def test_a_broken_slot_is_replaced_without_touching_the_others(self):
        script = Script(stop_after=6, outcomes=[BrokenProcessPool()])
        worker, slots = self.make_worker(2, script)
        delta = Delta(BREAKS)

        with self.assertLogs("analytics.extract_worker", "ERROR"):
            worker.run()

        self.assertEqual(len(slots), 3)
        broken, healthy, replacement = slots
        self.assertEqual(broken.shutdowns, [(False, True)])
        self.assertEqual(healthy.shutdowns, [(True, False)])
        self.assertEqual(replacement.shutdowns, [(True, False)])
        self.assertEqual(delta[BREAKS], 1)

    def test_replacing_a_dead_child_clears_its_active_chunk_only(self):
        worker, _ = self.make_worker(2, Script(stop_after=1))
        slots = [worker._executor_factory(), worker._executor_factory()]
        worker.chunk_starts[:] = [100, 200]
        with self.assertLogs("analytics.extract_worker", "ERROR"):
            worker._replace(slots, 0)
        self.assertEqual(list(worker.chunk_starts), [0, 200])

    def test_a_slot_whose_process_died_after_returning_is_replaced(self):
        # The chunk's future succeeds, so the break only shows up when the
        # next chunk is submitted.
        script = Script(stop_after=4, dies_after={1})
        worker, slots = self.make_worker(1, script)
        delta = Delta(BREAKS)

        with self.assertLogs("analytics.extract_worker", "ERROR"):
            worker.run()

        self.assertEqual(script.submissions, 4)
        self.assertEqual(len(slots), 2)
        died, replacement = slots
        self.assertEqual(died.shutdowns, [(False, True)])
        self.assertEqual(replacement.shutdowns, [(True, False)])
        self.assertEqual(delta[BREAKS], 1)

    def test_a_chunk_that_raises_is_logged_and_the_slot_carries_on(self):
        script = Script(stop_after=4, outcomes=[RuntimeError("boom")])
        worker, slots = self.make_worker(1, script)

        with self.assertLogs("analytics.extract_worker", "ERROR"):
            worker.run()

        self.assertEqual(script.submissions, 4)
        self.assertEqual(len(slots), 1)

    def test_signal_handlers_are_restored_afterwards(self):
        import signal

        before = signal.getsignal(signal.SIGTERM)
        worker, _ = self.make_worker(1, Script(stop_after=1))

        worker.run()

        self.assertIs(signal.getsignal(signal.SIGTERM), before)
        self.assertTrue(worker.stop_event.is_set())
