import threading
from datetime import timedelta

from django.contrib.gis.geos import Point
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from analytics.management.commands.free_stale_processing_tasks import _free_stale_tasks
from analytics.models import ExtractTask, ProcessingOption
from analytics.tasks.processing import _release_claimed_tasks, claim_pending_tasks
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection

PENDING, DONE, LOCKED, QUEUED, FAILED = 0, 1, 2, 3, -1


class DispatchTestCase(TestCase):
    """Claiming, releasing, and reaping of extract tasks.

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

    def refs(self, *tasks):
        """The (id, dataset_id) pairs a claim returns."""
        return [(t.id, t.dataset_id) for t in tasks]

    # --- claim_pending_tasks -------------------------------------------------

    def test_claim_orders_by_priority_then_age_and_marks_running(self):
        old = self.make_task(age=timedelta(hours=2))
        urgent = self.make_task(priority=1, age=timedelta(minutes=1))
        new = self.make_task()

        self.assertEqual(claim_pending_tasks(2), self.refs(urgent, old))
        self.assertEqual(self.statuses(urgent, old, new), [LOCKED, LOCKED, PENDING])

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
            claim_pending_tasks(3), self.refs(first, second, third)
        )

    def test_claim_tokens_match_database_and_preserve_priority_order(self):
        ordinary = self.make_task()
        urgent = self.make_task(priority=10)
        claimed = claim_pending_tasks(2, include_inputs=True)
        self.assertEqual([(claim.task_id, claim.dataset_id) for claim in claimed],
                         self.refs(urgent, ordinary))
        for task, claim in zip((urgent, ordinary), claimed):
            task.refresh_from_db()
            self.assertIsNotNone(claim.claimed_at)
            self.assertEqual(task.update_time, claim.claimed_at)
            self.assertEqual(task.resource_ids, claim.resource_ids)
            self.assertEqual(task.kwargs, claim.kwargs)
            self.assertEqual(task.po_id, claim.po_id)
            self.assertEqual(task.fm_id, claim.fm_id)

    def test_successive_claims_are_disjoint(self):
        a, b, c = self.make_task(), self.make_task(), self.make_task()

        first = claim_pending_tasks(2)
        second = claim_pending_tasks(2)

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 1)
        self.assertEqual(set(first) | set(second), set(self.refs(a, b, c)))
        self.assertEqual(claim_pending_tasks(2), [])

    def test_claim_ignores_non_pending_rows(self):
        for status in (DONE, LOCKED, QUEUED, FAILED):
            self.make_task(status=status)
        self.assertEqual(claim_pending_tasks(10), [])

    def test_claim_sends_the_same_parameters_however_many_rows_it_takes(self):
        # The aligned reference arrays and distinct-dataset filter use three
        # parameters in total, independent of the number of claimed rows.
        for _ in range(5):
            self.make_task()

        with CaptureQueriesContext(connection) as ctx:
            claimed = claim_pending_tasks(5)

        self.assertEqual(len(claimed), 5)
        [update] = [q["sql"] for q in ctx.captured_queries if "unnest" in q["sql"]]
        self.assertNotIn("VALUES", update)

    # --- _release_claimed_tasks ------------------------------------------------

    def test_release_returns_running_tasks_to_pending(self):
        a, b = self.make_task(), self.make_task()
        claimed = claim_pending_tasks(2)

        self.assertEqual(_release_claimed_tasks(claimed), 2)
        self.assertEqual(self.statuses(a, b), [PENDING, PENDING])
        self.assertEqual(claim_pending_tasks(2), claimed)

    def test_release_leaves_tasks_that_are_no_longer_running(self):
        # Finished, failed, or already reaped: none of those are the
        # releasing worker's to hand back.
        tasks = [self.make_task(status=s) for s in (LOCKED, DONE, FAILED, PENDING)]

        self.assertEqual(_release_claimed_tasks(self.refs(*tasks)), 1)
        self.assertEqual(self.statuses(*tasks), [PENDING, DONE, FAILED, PENDING])

    def test_releasing_nothing_issues_no_query(self):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(_release_claimed_tasks([]), 0)
        self.assertEqual(ctx.captured_queries, [])

    # --- _free_stale_tasks ------------------------------------------------------

    def test_reaper_frees_stale_running_and_queued_only(self):
        # Nothing writes queued (3) any more, but rows the Celery worker left
        # there must still drain.
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

        claimed_ids = [cid for r in results for cid, _ in (r or [])]
        self.assertEqual(len(claimed_ids), 20, "every task should be claimed exactly once")
        self.assertEqual(len(set(claimed_ids)), 20, "no task should be claimed twice")
        self.assertEqual(set(claimed_ids), {t.id for t in self.tasks})

        statuses = set(
            ExtractTask.objects.filter(id__in=[t.id for t in self.tasks]).values_list(
                "status", flat=True
            )
        )
        self.assertEqual(statuses, {LOCKED})
