import threading
from datetime import timedelta
from unittest import mock

from django.contrib.gis.geos import Point
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
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
        """Create a task. Distinct kwargs keep the (dataset_id, fm, po, resource_ids, kwargs) unique index happy."""
        type(self)._seq += 1
        task = ExtractTask.objects.create(
            resource_ids=[self.resource.id],
            dataset_id=self.resource.dataset_id,
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

    def test_claim_breaks_priority_and_submit_time_ties_by_id(self):
        # build_extract_tasks inserts in batches sharing one NOW() per
        # INSERT, so many real rows carry identical (priority, submit_time)
        # -- explicitly backdate all three to the exact same timestamp here
        # to reproduce that tie, rather than relying on auto_now_add's
        # natural (and not guaranteed-distinct) timing.
        tied_time = timezone.now() - timedelta(hours=1)
        first = self.make_task()
        second = self.make_task()
        third = self.make_task()
        ExtractTask.objects.filter(id__in=[first.id, second.id, third.id]).update(
            submit_time=tied_time, update_time=tied_time
        )

        self.assertEqual(
            claim_pending_tasks(3), [first.id, second.id, third.id]
        )

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

        self.assertEqual(result, [{"task_id": first.id, "results": 1}])
        self.assertEqual(self.statuses(first, second), [DONE, QUEUED])
        delay.assert_called_once_with([second.id])

    def test_noop_still_chains(self):
        # The row was already finished by the time its message arrived; the
        # chain must carry on regardless or every collision kills a worker.
        stale = self.make_task(status=DONE)
        pending = self.make_task()

        result, delay = self.run_task(stale, mock.Mock())

        self.assertEqual(result, [None])
        self.assertEqual(self.statuses(stale, pending), [DONE, QUEUED])
        delay.assert_called_once_with([pending.id])

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

        self.assertEqual(result, [{"task_id": first.id, "results": 0}])
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
        # limit counts tasks; each call fits its claim in one message.
        self.assertEqual(delay.call_count, 2)
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


class ClaimLockContentionTest(TransactionTestCase):
    """Real concurrent claimers, on real separate connections.

    claim_pending_tasks now serializes on pg_advisory_xact_lock (see its
    docstring): concurrent callers should queue on that lock and each walk
    away with a disjoint set of ids, rather than racing FOR UPDATE SKIP
    LOCKED against each other. This needs TransactionTestCase (real commits,
    real separate DB connections per thread) -- TestCase's single wrapping
    transaction can't reproduce genuine concurrency, per the note on
    DispatchTestCase above.
    """

    def setUp(self):
        dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        self.resource = DatasetResource.objects.create(
            dataset=dataset, name="ds-2020", path="2020.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        self.fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))

        self.tasks = []
        tied_time = timezone.now() - timedelta(hours=1)
        for n in range(20):
            task = ExtractTask.objects.create(
                resource_ids=[self.resource.id],
                dataset_id=self.resource.dataset_id,
                fm=self.fm,
                po=self.po,
                kwargs={"n": n},
            )
            self.tasks.append(task)
        ExtractTask.objects.filter(id__in=[t.id for t in self.tasks]).update(
            submit_time=tied_time, update_time=tied_time
        )

    def test_concurrent_single_claims_are_disjoint_and_complete(self):
        results = [None] * 20
        errors = []

        def claim_one(i):
            try:
                results[i] = claim_pending_tasks(1)
            except Exception as exc:  # pragma: no cover - surfaced via errors below
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=claim_one, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertTrue(all(t.is_alive() is False for t in threads))

        claimed_ids = [cid for r in results for cid in (r or [])]
        self.assertEqual(len(claimed_ids), 20, "every task should be claimed exactly once")
        self.assertEqual(len(set(claimed_ids)), 20, "no task should be claimed twice")
        self.assertEqual(set(claimed_ids), {t.id for t in self.tasks})

        statuses = set(
            ExtractTask.objects.filter(id__in=[t.id for t in self.tasks]).values_list(
                "status", flat=True
            )
        )
        self.assertEqual(statuses, {QUEUED})


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

    @override_settings(EXTRACT_TASK_CLAIM_BATCH=4)
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
        # 13 idle slots, one message each, four tasks per message.
        run.assert_called_once_with(limit=13 * 4)

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


class ClaimBatchingTests(TestCase):
    """One claim per message instead of one claim per task.

    Every claim serializes on CLAIM_LOCK_ID while holding a pooler
    connection, so the claim rate -- not the work -- was what filled the
    connection pool. Batching divides that rate by the batch size.
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

    def make_task(self, *, status=PENDING):
        type(self)._seq += 1
        return ExtractTask.objects.create(
            resource_ids=[self.resource.id],
            dataset_id=self.resource.dataset_id,
            fm=self.fm,
            po=self.po,
            status=status,
            kwargs={"n": self._seq},
        )

    def test_one_message_carries_a_whole_batch(self):
        tasks = [self.make_task() for _ in range(4)]

        with (
            mock.patch.object(run_extract_task, "delay") as delay,
            self.settings(EXTRACT_TASK_CLAIM_BATCH=4),
        ):
            claimed = processing.dispatch_pending_tasks()

        self.assertEqual(len(claimed), 4)
        delay.assert_called_once_with([t.id for t in tasks])

    def test_claim_is_issued_once_per_batch_not_once_per_task(self):
        for _ in range(4):
            self.make_task()

        with (
            mock.patch.object(run_extract_task, "delay"),
            mock.patch.object(
                processing, "claim_pending_tasks", wraps=processing.claim_pending_tasks
            ) as claim,
            self.settings(EXTRACT_TASK_CLAIM_BATCH=4),
        ):
            processing.dispatch_pending_tasks()

        # The whole point: one advisory lock acquisition for the batch.
        claim.assert_called_once_with(4)

    def test_finishing_a_batch_dispatches_exactly_one_batch(self):
        # The fleet holds one in-flight message per worker slot. If a chain
        # published one message per task it finished, each completion would
        # fan out 4x and the queue would grow without bound.
        running = [self.make_task(status=QUEUED) for _ in range(4)]
        for _ in range(8):
            self.make_task()

        with (
            mock.patch.object(processing, "get_func", return_value=lambda g, p, **kw: []),
            mock.patch.object(run_extract_task, "delay") as delay,
            self.settings(EXTRACT_TASK_CLAIM_BATCH=4),
        ):
            run_extract_task([t.id for t in running])

        self.assertEqual(
            delay.call_count, 1,
            "one message in must produce exactly one message out",
        )
        self.assertEqual(len(delay.call_args.args[0]), 4)

    def test_one_failure_does_not_strand_the_rest_of_the_batch(self):
        # The other three are already claimed (status=3); aborting the message
        # would leave nothing to run them until the stale reaper fires.
        tasks = [self.make_task(status=QUEUED) for _ in range(4)]
        seen = []

        def flaky(geometry, path, **kw):
            seen.append(path)
            if len(seen) == 1:
                raise RuntimeError("boom")
            return [("mean", 1.0)]

        with (
            mock.patch.object(processing, "get_func", return_value=flaky),
            mock.patch.object(run_extract_task, "delay"),
            self.assertRaises(RuntimeError),
        ):
            run_extract_task([t.id for t in tasks])

        statuses = [ExtractTask.objects.get(id=t.id).status for t in tasks]
        self.assertEqual(statuses[0], FAILED)
        self.assertEqual(
            statuses[1:], [DONE] * 3,
            "a failure in the first task stranded the rest of the batch",
        )

    def test_a_bare_task_id_from_an_older_pod_still_runs(self):
        # Rolling deploys mean messages published by the previous build are
        # still in the queue when the new one starts consuming.
        task = self.make_task(status=QUEUED)

        with (
            mock.patch.object(processing, "get_func", return_value=lambda g, p, **kw: []),
            mock.patch.object(run_extract_task, "delay"),
        ):
            result = run_extract_task(task.id)

        self.assertEqual(result, [{"task_id": task.id, "results": 0}])
        self.assertEqual(ExtractTask.objects.get(id=task.id).status, DONE)

    def test_batch_size_is_configurable(self):
        for _ in range(6):
            self.make_task()

        with (
            mock.patch.object(run_extract_task, "delay") as delay,
            self.settings(EXTRACT_TASK_CLAIM_BATCH=2),
        ):
            processing.dispatch_pending_tasks()

        self.assertEqual(len(delay.call_args.args[0]), 2)

    def test_a_partial_final_batch_is_still_dispatched(self):
        # 5 tasks at batch size 4 must go out as 4 + 1, not 4 with one left
        # claimed but never published.
        for _ in range(5):
            self.make_task()

        with (
            mock.patch.object(run_extract_task, "delay") as delay,
            self.settings(EXTRACT_TASK_CLAIM_BATCH=4),
        ):
            claimed = processing.dispatch_pending_tasks(limit=5)

        self.assertEqual(len(claimed), 5)
        self.assertEqual([len(c.args[0]) for c in delay.call_args_list], [4, 1])
