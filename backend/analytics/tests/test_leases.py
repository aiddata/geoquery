"""Pair cursor leases: claim, compute, complete and recover (analytics.tasks.leases)."""

import threading
import time
import uuid
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.gis.geos import Point, Polygon
from django.db import connection
from django.db.models.expressions import RawSQL
from django.test import TestCase, override_settings
from django.utils import timezone
from prometheus_client import REGISTRY

from analytics.coverage import run_coverage_chunk
from analytics.models import (
    ExtractData, ExtractInputState, ExtractTask, ExtractTaskBuildProgress, ExtractTaskLease,
)
from analytics.tasks import leases
from analytics.tasks.leases import claim_lease, complete_lease, run_lease
from analytics.changes import mark
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin


def mean_of_x(geometry, path, **kwargs):
    """A processor whose value identifies the feature: its centroid's x."""
    return [(kwargs["name"], round(geometry.centroid.x, 3))]


class LeaseTestCase(TestCase):
    processor = staticmethod(mean_of_x)

    @classmethod
    def setUpTestData(cls):
        cls.dataset, cls.po, (cls.resource,) = make_dataset("lease")
        cls.fc, cls.fms = make_collection("lease-fc", 10)
        settle_inputs()
        cls.pair = ExtractTaskBuildProgress.objects.get(dataset_id=cls.dataset.id, current=True)

    def setUp(self):
        patcher = mock.patch.object(leases, "get_func", return_value=self.processor)
        patcher.start()
        self.addCleanup(patcher.stop)
        batch = mock.patch.object(leases, "get_batch_func", return_value=None)
        batch.start()
        self.addCleanup(batch.stop)

    def lease_row(self, lease):
        return ExtractTaskLease.objects.filter(id=lease.id).first()

    def tasks(self):
        return ExtractTask.objects.filter(dataset_id=self.dataset.id)

    def run_page(self, lease, stop_event=None):
        with self.captureOnCommitCallbacks(execute=True):
            return run_lease(lease, stop_event)


class ClaimTests(LeaseTestCase):
    def test_a_new_page_is_leased_and_the_cursor_advances_in_the_same_transaction(self):
        lease = claim_lease()
        self.assertEqual(lease.fm_ids, [fm.id for fm in self.fms])
        self.assertEqual(lease.attempts, 1)
        row = self.lease_row(lease)
        self.assertEqual(row.token, lease.token)
        self.assertEqual(row.input_generations, lease.generations.as_json())
        self.pair.refresh_from_db()
        self.assertEqual(self.pair.cursor_fm_id, self.fms[-1].id)
        self.assertIsNone(claim_lease())

    @override_settings(EXTRACT_TASK_LEASE_PAGE_SIZE=3, EXTRACT_TASK_LEASE_BLOCK_SIZE=3)
    def test_a_full_page_stops_the_cursor_at_its_last_feature(self):
        first, second = claim_lease(), claim_lease()
        self.assertEqual(first.fm_ids, [fm.id for fm in self.fms[:3]])
        self.assertEqual(second.fm_ids, [fm.id for fm in self.fms[3:6]])
        self.pair.refresh_from_db()
        self.assertEqual(self.pair.cursor_fm_id, self.fms[5].id)

    def test_a_scan_window_bounds_each_claim(self):
        start = self.fms[0].id - 1
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=start)
        with self.settings(EXTRACT_TASK_LEASE_SCAN_WINDOW=2):
            lease = claim_lease()
        self.assertEqual(lease.fm_ids, [fm.id for fm in self.fms if fm.id <= start + 2])

    def test_a_claim_yields_after_ten_empty_windows(self):
        start = self.fms[0].id - 100
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=start)
        with self.settings(EXTRACT_TASK_LEASE_SCAN_WINDOW=2):
            self.assertIsNone(claim_lease())
        self.pair.refresh_from_db()
        self.assertEqual(self.pair.cursor_fm_id, start + 20)

    def test_windows_with_nothing_to_lease_advance_the_cursor(self):
        for fm in self.fms:
            ExtractTask.objects.create(
                dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=fm, po=self.po,
                priority=1,
            )
        self.assertIsNone(claim_lease())
        self.pair.refresh_from_db()
        self.assertEqual(self.pair.cursor_fm_id, self.fms[-1].id)

    def test_existing_default_tasks_are_skipped_but_custom_kwargs_tasks_are_not(self):
        ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=self.fms[0], po=self.po,
        )
        ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=self.fms[1], po=self.po,
            kwargs={"band": 2},
        )
        lease = claim_lease()
        self.assertNotIn(self.fms[0].id, lease.fm_ids)
        self.assertIn(self.fms[1].id, lease.fm_ids)

    def test_resetting_pairs_inactive_collections_and_uploads_are_not_leased(self):
        DatasetResource.objects.filter(id=self.resource.id).update(path="v2.tif")
        self.assertIsNone(claim_lease())
        settle_inputs()

        off, off_fms = make_collection("lease-off", 2, active=False)
        upload, up_fms = make_collection("lease-up", 2, upload=True)
        settle_inputs()
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=self.fms[-1].id)
        self.assertIsNone(claim_lease())
        self.pair.refresh_from_db()
        # Uploads never move a cap: the cursor stops at the last eligible feature.
        self.assertEqual(self.pair.cursor_fm_id, off_fms[-1].id)

        # Reactivation rewinds below the collection, and its features come back.
        FeatureCollection.objects.filter(id=off.id).update(active=True)
        settle_inputs()
        self.assertEqual(claim_lease().fm_ids, [fm.id for fm in off_fms])

    def test_a_non_global_pair_never_scans_past_its_coverage(self):
        extent = Polygon(((0, 0), (3, 0), (3, 1), (0, 1), (0, 0)))
        local, po, _ = make_dataset("lease-local", is_global=False, extent=extent)
        settle_inputs()
        pair = ExtractTaskBuildProgress.objects.get(dataset_id=local.id)
        claimed = [claim_lease() for _ in range(2)]  # the global pair's page, then nothing
        self.assertEqual([l.dataset_id for l in claimed if l], [self.dataset.id])

        while run_coverage_chunk() is not None:
            pass
        lease = claim_lease()
        self.assertEqual(lease.progress_id, pair.id)
        self.assertEqual(lease.fm_ids, [fm.id for fm in self.fms[:3]])

    def test_a_rewind_never_hands_out_features_already_in_a_lease(self):
        first = claim_lease()
        _, (added,) = make_collection("lease-more", 1)
        mark("dataset", [self.dataset.id], rewind_from=0)
        settle_inputs()
        self.pair.refresh_from_db()
        self.assertEqual(self.pair.cursor_fm_id, 0)
        # A rewind invalidates nothing: the outstanding lease keeps its token,
        # and the rescan from 0 finds only the new feature.
        self.assertEqual(self.lease_row(first).token, first.token)
        fresh = claim_lease()
        self.assertEqual(fresh.fm_ids, [added.id])

    def test_the_coverage_rule_is_read_under_the_guard(self):
        # The reviewer's reproduction: the dataset turns non-global, and sync
        # publishes it, between the pair's first read and the guard. The
        # claim must use the new rule (watermark 0), not the one it read.
        real, flipped = leases.lock_states, []

        def flip_first(*args, **kwargs):
            if not flipped:
                flipped.append(True)
                Dataset.objects.filter(id=self.dataset.id).update(
                    is_global=False, spatial_extent=Polygon(((0, 0), (9, 0), (9, 9), (0, 9), (0, 0))))
                settle_inputs()
            return real(*args, **kwargs)

        with mock.patch.object(leases, "lock_states", flip_first):
            self.assertIsNone(claim_lease())
        self.assertTrue(flipped)
        self.assertFalse(ExtractTaskLease.objects.exists())

    def test_a_reshaped_feature_is_recomputed_by_a_lease(self):
        self.assertEqual(self.run_page(claim_lease()), "completed")
        reshaped = self.fms[3]
        Feature.objects.filter(id=reshaped.geom_id).update(shape=Point(70.5, 0.5))
        settle_inputs()
        # Only that feature's background task was deleted, and only it is leased again.
        lease = claim_lease()
        self.assertEqual(lease.fm_ids, [reshaped.id])
        self.assertEqual(self.run_page(lease), "completed")
        self.assertEqual(self.tasks().get(fm_id=reshaped.id).status, 1)
        self.assertEqual(self.tasks().count(), len(self.fms))

    def test_pages_are_sized_by_a_pairs_pace(self):
        self.assertEqual(leases._page_size(None, 1), settings.EXTRACT_TASK_LEASE_PAGE_SIZE)
        # A twelve-resource grouped pair starts at a twelfth of the page.
        self.assertEqual(leases._page_size(None, 12), settings.EXTRACT_TASK_LEASE_PAGE_SIZE // 12)
        # Once measured: a quarter of the lease at that pace, at least one.
        quarter = settings.EXTRACT_TASK_LEASE_SECONDS / 4
        self.assertEqual(leases._page_size(quarter / 3, 1), 3)
        self.assertEqual(leases._page_size(quarter * 10, 1), 1)
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(seconds_per_feature=quarter / 3)
        self.assertEqual(len(claim_lease().fm_ids), 3)

    def test_disabled_leases_assign_nothing(self):
        with self.settings(EXTRACT_TASK_LEASES_ENABLED=False):
            self.assertIsNone(claim_lease())


class CompleteTests(LeaseTestCase):
    def test_a_page_inserts_terminal_tasks_with_results_and_deletes_the_lease(self):
        lease = claim_lease()
        self.assertEqual(self.run_page(lease), "completed")
        self.assertIsNone(self.lease_row(lease))
        tasks = list(self.tasks().order_by("fm_id"))
        self.assertEqual([t.fm_id for t in tasks], [fm.id for fm in self.fms])
        for i, task in enumerate(tasks):
            self.assertEqual((task.status, task.pair_id, task.attempts), (1, self.pair.id, 0))
            self.assertIsNotNone(task.complete_time)
            row = ExtractData.objects.get(dataset_id=self.dataset.id, extract_task_id=task.id)
            self.assertEqual(row.float_value, i + 0.5)

    def test_feature_failures_become_failed_tasks_without_stopping_the_page(self):
        def picky(geometry, path, **kwargs):
            if geometry.centroid.x < 1:
                raise RuntimeError("bad pixel")
            return mean_of_x(geometry, path, **kwargs)

        with mock.patch.object(leases, "get_func", return_value=picky):
            self.run_page(claim_lease())
        first = self.tasks().get(fm=self.fms[0])
        self.assertEqual(first.status, -1)
        self.assertIn("bad pixel", first.error)
        self.assertEqual(self.tasks().filter(status=1).count(), 9)

    def test_a_requests_task_wins_and_keeps_its_own_results(self):
        lease = claim_lease()
        request_task = ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=self.fms[4],
            po=self.po, priority=1,
        )
        self.run_page(lease)
        request_task.refresh_from_db()
        self.assertEqual((request_task.status, request_task.pair_id), (0, None))
        self.assertFalse(ExtractData.objects.filter(
            dataset_id=self.dataset.id, extract_task_id=request_task.id).exists())
        self.assertEqual(self.tasks().filter(status=1).count(), 9)

    def test_committed_features_are_counted_by_dataset_and_outcome(self):
        def count(outcome):
            labels = {"dataset_id": str(self.dataset.id), "outcome": outcome}
            return REGISTRY.get_sample_value("geoquery_extract_lease_features_total", labels) or 0

        before = {outcome: count(outcome) for outcome in ("completed", "conflict")}
        lease = claim_lease()
        ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=self.fms[4],
            po=self.po, priority=1,
        )
        self.run_page(lease)
        self.assertEqual(count("completed") - before["completed"], 9)
        self.assertEqual(count("conflict") - before["conflict"], 1)

    def test_a_stale_token_writes_nothing(self):
        lease = claim_lease()
        ExtractTaskLease.objects.filter(id=lease.id).update(token=uuid.uuid4())
        self.assertEqual(self.run_page(lease), "stale")
        self.assertFalse(self.tasks().exists())
        self.assertIsNotNone(self.lease_row(lease))

    def test_an_addition_does_not_disturb_a_page_in_flight(self):
        lease = claim_lease()
        FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(40, 40)))
        DatasetResource.objects.create(dataset=self.dataset, name="lease-r2", path="r2.tif")
        self.assertEqual(self.run_page(lease), "completed")
        self.assertEqual(self.tasks().count(), len(self.fms))

    def test_changed_inputs_defer_the_page_without_penalty(self):
        lease = claim_lease()
        Feature.objects.filter(id=self.fms[0].geom_id).update(shape=Point(40, 40))
        self.assertEqual(self.run_page(lease), "deferred")
        self.assertFalse(self.tasks().exists())
        row = self.lease_row(lease)
        self.assertNotEqual(row.token, lease.token)
        self.assertEqual(row.attempts, 0)
        self.assertLessEqual(row.leased_until, timezone.now())

    def test_an_inactive_dataset_parks_the_page(self):
        lease = claim_lease()
        outcomes = leases._compute(lease, leases._load_inputs(lease, leases._Reader()),
                                   leases._Reader(), lambda: None)
        # Deactivated after the guard snapshot: simulate by flipping the row
        # behind the trigger's back is impossible, so deactivate and settle,
        # then complete under fresh generations.
        Dataset.objects.filter(id=self.dataset.id).update(active=False)
        settle_inputs()
        lease = claim_lease() or lease
        row = self.lease_row(lease)
        lease.token = row.token
        lease.generations = leases.Generations.from_json(row.input_generations)
        with mock.patch.object(leases, "recheck", return_value=True):
            self.assertEqual(complete_lease(lease, outcomes), "parked")
        self.assertIsNotNone(self.lease_row(lease))
        self.assertIsNone(claim_lease())  # parked leases are not taken over

    def test_a_lost_commit_response_is_harmless(self):
        lease = claim_lease()
        outcomes = leases._compute(lease, leases._load_inputs(lease, leases._Reader()),
                                   leases._Reader(), lambda: None)
        self.assertEqual(complete_lease(lease, outcomes), "completed")
        self.assertEqual(complete_lease(lease, outcomes), "gone")
        self.assertEqual(self.tasks().count(), 10)

    def test_transient_database_errors_retry_the_whole_transaction(self):
        from django.db import OperationalError

        lease = claim_lease()
        outcomes = leases._compute(lease, leases._load_inputs(lease, leases._Reader()),
                                   leases._Reader(), lambda: None)
        real = leases._complete_once
        calls = []

        def flaky(*args):
            calls.append(1)
            if len(calls) == 1:
                raise OperationalError("connection reset")
            return real(*args)

        with mock.patch.object(leases, "_complete_once", side_effect=flaky), \
                mock.patch.object(leases.time, "sleep"), self.assertLogs(leases.logger, "WARNING"):
            self.assertEqual(complete_lease(lease, outcomes), "completed")
        self.assertEqual(len(calls), 2)

    def test_setup_errors_become_explicit_failed_tasks(self):
        DatasetResource.objects.filter(id=self.resource.id).update(path=self.resource.path)
        lease = claim_lease()
        with mock.patch.object(leases, "get_func", side_effect=ValueError("Operation nope not supported.")):
            self.run_page(lease)
        self.assertEqual(set(self.tasks().values_list("status", flat=True)), {-1})
        self.assertIn("setup", self.tasks().first().error)

    def test_unstoreable_values_fail_only_their_own_feature(self):
        def overflowing(geometry, path, **kwargs):
            if geometry.centroid.x < 1:
                return [(kwargs["name"], 2 ** 70)]  # beyond bigint
            if geometry.centroid.x < 2:
                return [(kwargs["name"], "nul\x00byte")]  # undumpable text
            return mean_of_x(geometry, path, **kwargs)

        with mock.patch.object(leases, "get_func", return_value=overflowing), \
                self.assertLogs(leases.logger, "WARNING"):
            self.assertEqual(self.run_page(claim_lease()), "completed")
        bad = list(self.tasks().filter(fm__in=self.fms[:2]))
        self.assertEqual([t.status for t in bad], [-1, -1])
        self.assertFalse(ExtractData.objects.filter(extract_task_id__in=[t.id for t in bad]).exists())
        self.assertEqual(self.tasks().filter(status=1).count(), 8)
        self.assertIsNone(ExtractTaskLease.objects.first())

    def test_batch_processors_open_each_resource_once_per_block(self):
        opened = []

        def batch(feats, path, **kwargs):
            opened.append(len(feats))
            for i, feat in enumerate(feats):
                yield i, mean_of_x(feat, path, **kwargs)

        with mock.patch.object(leases, "get_batch_func", return_value=batch), \
                self.settings(EXTRACT_TASK_LEASE_BLOCK_SIZE=4):
            self.run_page(claim_lease())
        self.assertEqual(opened, [4, 4, 2])
        self.assertEqual(self.tasks().filter(status=1).count(), 10)



class StandbyReadTests(ReplicaReadsTestMixin, LeaseTestCase):
    def test_standby_reads_wait_for_the_claim_and_give_the_same_results(self):
        with self.settings(EXTRACT_TASK_LEASE_READ_REPLICA=True):
            lease = claim_lease()
            reader = leases._Reader()
            self.assertEqual(reader.alias, "replica")
            self.assertEqual(self.run_page(lease), "completed")
        self.assertEqual(self.tasks().filter(status=1).count(), 10)

    def test_a_standby_that_does_not_catch_up_in_time_is_not_used(self):
        with self.settings(EXTRACT_TASK_LEASE_READ_REPLICA=True,
                           EXTRACT_TASK_LEASE_REPLICA_WAIT_SECONDS=0.01), \
                mock.patch.object(leases._Reader, "_wait_for", return_value=False):
            self.assertEqual(leases._Reader().alias, "default")


class RecoveryTests(LeaseTestCase):
    def expire(self, lease, **fields):
        # The database's now(), not the wall clock (or Django's Now(), which
        # is statement_timestamp()): inside a TestCase it is fixed at the
        # start of the class's transaction, which due checks compare against.
        ExtractTaskLease.objects.filter(id=lease.id).update(
            leased_until=RawSQL("now() - interval '1 second'", []), **fields)

    def test_an_expired_lease_is_taken_over_first_under_a_new_token(self):
        lease = claim_lease()
        self.expire(lease)
        again = claim_lease()
        self.assertEqual(again.id, lease.id)
        self.assertTrue(again.takeover)
        self.assertNotEqual(again.token, lease.token)
        self.assertEqual(again.attempts, 2)
        # The first owner's late completion is discarded.
        self.assertEqual(self.run_page(lease), "stale")
        self.assertEqual(self.run_page(again), "completed")

    def test_a_backed_off_lease_waits_for_its_retry_time(self):
        lease = claim_lease()
        self.expire(lease, retry_after=timezone.now() + timedelta(minutes=5))
        self.assertIsNone(claim_lease())

    def test_repeated_failure_splits_the_page(self):
        lease = claim_lease()
        self.expire(lease, attempts=settings.EXTRACT_TASK_LEASE_BISECT_ATTEMPT)
        child = claim_lease()
        self.assertEqual(child.id, lease.id)
        self.assertEqual(child.fm_ids, [fm.id for fm in self.fms[:5]])
        self.assertEqual(child.attempts, 1)
        sibling = ExtractTaskLease.objects.exclude(id=lease.id).get()
        self.assertEqual(sibling.fm_ids, [fm.id for fm in self.fms[5:]])
        self.assertEqual(sibling.attempts, 0)
        self.assertLessEqual(sibling.leased_until, timezone.now())

    def test_a_takeover_guards_the_collection_its_features_are_in_now(self):
        # The reviewer's other reproduction: a feature moves to another
        # collection between the takeover's first read and its guards.
        lease = claim_lease()
        self.expire(lease)
        other = FeatureCollection.objects.create(name="lease-moved", path="/data/lease-moved", active=True)
        real, moved = leases.lock_states, []

        def move_first(*args, **kwargs):
            if not moved:
                moved.append(True)
                FeatMap.objects.filter(id=self.fms[0].id).update(fc=other)
            return real(*args, **kwargs)

        with mock.patch.object(leases, "lock_states", move_first):
            self.assertIsNone(leases._take_over_due_lease())
        again = leases._take_over_due_lease()
        self.assertIn(other.id, again.generations.collections)

    def test_a_page_that_ran_out_of_time_is_cut_to_the_pairs_pace(self):
        lease = claim_lease()
        self.assertEqual(len(lease.fm_ids), len(self.fms))
        quarter = settings.EXTRACT_TASK_LEASE_SECONDS / 4
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(seconds_per_feature=quarter / 2)
        self.expire(lease, attempts=1)
        again = claim_lease()
        self.assertEqual((again.id, again.fm_ids, again.attempts), (lease.id, lease.fm_ids[:2], 1))
        rest = ExtractTaskLease.objects.exclude(id=lease.id).get()
        self.assertEqual((rest.fm_ids, rest.attempts), (lease.fm_ids[2:], 0))

    def test_a_finished_page_records_its_pace(self):
        self.assertEqual(self.run_page(claim_lease()), "completed")
        self.pair.refresh_from_db()
        self.assertIsNotNone(self.pair.seconds_per_feature)

    def test_an_isolated_feature_fails_terminally_after_its_budget(self):
        with self.settings(EXTRACT_TASK_LEASE_PAGE_SIZE=1, EXTRACT_TASK_LEASE_BLOCK_SIZE=1):
            lease = claim_lease()
        self.expire(lease, attempts=settings.MAX_EXTRACT_TASK_ATTEMPTS, last_error="segfault")
        claim_lease()  # records the failure, then leases the next page
        task = self.tasks().get(fm_id=lease.fm_ids[0])
        self.assertEqual((task.status, task.attempts, task.error, task.pair_id),
                         (-1, settings.MAX_EXTRACT_TASK_ATTEMPTS, "segfault", self.pair.id))
        self.assertIsNone(self.lease_row(lease))

    def test_deleted_members_are_dropped_only_after_confirmation(self):
        lease = claim_lease()
        self.expire(lease)
        self.fms[0].geom.delete()
        settle_inputs()  # the collection publish drops it from the lease
        again = claim_lease()
        self.assertNotIn(self.fms[0].id, again.fm_ids)
        self.assertEqual(len(again.fm_ids), 9)

    def test_a_graceful_stop_returns_the_page_with_its_attempt_refunded(self):
        lease = claim_lease()
        stop = threading.Event()
        stop.set()
        with self.settings(EXTRACT_WORKER_DRAIN_SECONDS=0.0001):
            calls = []

            def slow(geometry, path, **kwargs):
                calls.append(1)
                time.sleep(0.01)
                return mean_of_x(geometry, path, **kwargs)

            with mock.patch.object(leases, "get_func", return_value=slow), \
                    self.assertLogs(leases.logger, "WARNING"):
                self.assertEqual(self.run_page(lease, stop), "returned")
        row = self.lease_row(lease)
        self.assertNotEqual(row.token, lease.token)
        self.assertEqual(row.attempts, 0)
        self.assertLessEqual(row.leased_until, timezone.now())
        self.assertFalse(self.tasks().exists())
        self.assertLess(len(calls), 10)

    def test_a_page_that_outlives_its_lease_is_given_back_and_counts(self):
        lease = claim_lease()
        lease.assigned_at -= settings.EXTRACT_TASK_LEASE_SECONDS
        with self.assertLogs(leases.logger, "WARNING"):
            self.assertEqual(self.run_page(lease), "timed_out")
        self.assertEqual(self.lease_row(lease).attempts, 1)

    def test_an_unexpected_error_counts_and_backs_off(self):
        lease = claim_lease()
        with mock.patch.object(leases, "_load_inputs", side_effect=KeyError("surprise")), \
                self.assertLogs(leases.logger, "ERROR"):
            self.assertEqual(self.run_page(lease), "failed")
        row = self.lease_row(lease)
        self.assertEqual(row.attempts, 1)
        self.assertGreater(row.retry_after, timezone.now())
        self.assertIn("surprise", row.last_error)

    def test_a_database_failure_returns_the_page_unpenalized_and_raises(self):
        from django.db import OperationalError

        lease = claim_lease()
        with mock.patch.object(leases, "_load_inputs", side_effect=OperationalError("gone")), \
                self.assertRaises(leases.InfrastructureError):
            self.run_page(lease)
        self.assertEqual(self.lease_row(lease).attempts, 0)


class HashCollisionTests(TestCase):
    """Two different resource arrays with the same 32-bit hash.

    The unique index keys on the hash, so a lease's insert for one array
    conflicts with an existing task for the other. That is not "already
    done": the pair is backed off with a visible error and the work kept.
    """

    @classmethod
    def setUpTestData(cls):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT min(n), max(n) FROM (
                    SELECT n, extract_tasks_resource_ids_hash(ARRAY[n]) AS h
                    FROM generate_series(1000, 400000) n
                ) hashed
                GROUP BY h HAVING count(*) > 1
                LIMIT 1
                """
            )
            cls.ours, cls.theirs = cursor.fetchone()
        cls.dataset, cls.po, _ = make_dataset("collide", resources=0)
        DatasetResource.objects.create(id=cls.ours, dataset=cls.dataset, name="collide-r", path="r.tif")
        cls.fc, cls.fms = make_collection("collide-fc", 2)
        settle_inputs()
        cls.pair = ExtractTaskBuildProgress.objects.get(dataset_id=cls.dataset.id, current=True)

    def colliding_task(self, fm):
        return ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.theirs], fm=fm, po=self.po,
        )

    def test_a_collision_at_claim_keeps_the_cursor_and_backs_off_the_pair(self):
        self.colliding_task(self.fms[0])
        with self.assertLogs(leases.logger, "ERROR"):
            self.assertIsNone(claim_lease())
        self.pair.refresh_from_db()
        self.assertEqual(self.pair.cursor_fm_id, 0)
        self.assertIn("collision", self.pair.last_error)
        self.assertGreater(self.pair.retry_after, timezone.now())

    def test_a_collision_at_completion_keeps_the_lease(self):
        lease = claim_lease()
        self.colliding_task(self.fms[1])
        with mock.patch.object(leases, "get_func", return_value=mean_of_x), \
                mock.patch.object(leases, "get_batch_func", return_value=None), \
                self.assertLogs(leases.logger, "ERROR"):
            self.assertEqual(run_lease(lease), "collision")
        self.assertTrue(ExtractTaskLease.objects.filter(id=lease.id).exists())
        self.assertFalse(ExtractTask.objects.filter(dataset_id=self.dataset.id, pair_id=self.pair.id).exists())
        self.pair.refresh_from_db()
        self.assertIn("collision", self.pair.last_error)
