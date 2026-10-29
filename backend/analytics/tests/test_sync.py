"""Reconciliation: pairs, resets, rewinds and publishing (analytics.sync)."""

import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.contrib.gis.geos import Point, Polygon
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone as dj_timezone

from analytics import sync
from analytics.changes import mark
from analytics.models import (
    CoverageProgress, ExtractData, ExtractInputState, ExtractInvalidItem, ExtractTask,
    ExtractTaskBuildProgress, ExtractTaskLease, Request, RequestMap,
)
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature

UTC = timezone.utc


def state(kind, object_id):
    return ExtractInputState.objects.get(kind=kind, object_id=object_id)


def current_sets(dataset):
    return {
        (tuple(p.resource_ids), p.po_id)
        for p in ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id, current=True)
    }


def make_lease(pair, fm_ids, **fields):
    return ExtractTaskLease.objects.create(
        progress=pair, dataset_id=pair.dataset_id, resource_ids=pair.resource_ids,
        po_id=pair.po_id, fm_ids=fm_ids, token=uuid.uuid4(),
        leased_until=dj_timezone.now() + timedelta(minutes=30), **fields,
    )


class PairSyncTests(TestCase):
    def test_a_standard_dataset_gets_one_pair_per_resource_and_option(self):
        dataset, po, resources = make_dataset("std", resources=3)
        settle_inputs()
        self.assertEqual(current_sets(dataset), {((r.id,), po.id) for r in resources})
        for pair in ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id):
            self.assertIsNone(pair.bucket)
            self.assertEqual(pair.cursor_fm_id, 0)

    def test_a_grouped_dataset_gets_one_pair_per_bucket(self):
        dataset, po, resources = make_dataset("grp", resources=24, period="year")
        settle_inputs()
        pairs = ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id, current=True).order_by("bucket")
        self.assertEqual(
            [(p.bucket.year, len(p.resource_ids), p.task_group_period) for p in pairs],
            [(2020, 12, "year"), (2021, 12, "year")],
        )
        for pair in pairs:
            self.assertEqual(pair.resource_ids, sorted(pair.resource_ids))

    def test_buckets_are_utc(self):
        # 2020-12-31 23:30 in UTC-5 is 2021-01-01 04:30 UTC: next year's bucket.
        late = datetime(2020, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
        dataset, po, resources = make_dataset(
            "utc", resources=2, period="year",
            temporal=[datetime(2021, 6, 1, tzinfo=UTC), late],
        )
        settle_inputs()
        [pair] = ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id, current=True)
        self.assertEqual(pair.bucket.year, 2021)
        self.assertEqual(sorted(pair.resource_ids), sorted(r.id for r in resources))

    def test_a_changed_bucket_selects_a_new_set_and_never_rewrites_arrays(self):
        dataset, po, resources = make_dataset("abc", resources=2, period="year")
        settle_inputs()
        [a] = ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id, current=True)
        a_ids = list(a.resource_ids)
        ExtractTaskBuildProgress.objects.filter(id=a.id).update(cursor_fm_id=77)

        # A -> B: a third resource joins the bucket.
        extra = DatasetResource.objects.create(
            dataset=dataset, name="abc-extra", path="x.tif", temporal=datetime(2020, 6, 1, tzinfo=UTC),
        )
        settle_inputs()
        a.refresh_from_db()
        self.assertFalse(a.current)
        self.assertEqual(a.resource_ids, a_ids)
        [b] = ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id, current=True)
        self.assertEqual(sorted(b.resource_ids), sorted(a_ids + [extra.id]))

        # B -> C: a different resource leaves.
        resources[0].delete()
        settle_inputs()
        [c] = ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id, current=True)
        self.assertEqual(sorted(c.resource_ids), sorted([resources[1].id, extra.id]))
        self.assertEqual(ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id).count(), 3)

    def test_returning_to_an_earlier_set_reactivates_it_from_zero(self):
        dataset, po, resources = make_dataset("aba", resources=2, period="year")
        settle_inputs()
        [a] = ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id, current=True)
        ExtractTaskBuildProgress.objects.filter(id=a.id).update(cursor_fm_id=50)
        extra = DatasetResource.objects.create(
            dataset=dataset, name="aba-extra", path="x.tif", temporal=datetime(2020, 6, 1, tzinfo=UTC),
        )
        settle_inputs()
        extra.delete()
        settle_inputs()
        a.refresh_from_db()
        self.assertTrue(a.current)
        self.assertEqual(a.cursor_fm_id, 0)
        self.assertEqual(ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id).count(), 2)

    def test_an_emptied_bucket_retires_its_last_pair(self):
        dataset, po, resources = make_dataset("empty-bucket", resources=13, period="year")
        settle_inputs()
        resources[12].delete()  # the only 2021 resource
        settle_inputs()
        self.assertEqual(
            [p.bucket.year for p in ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id, current=True)],
            [2020],
        )

    def test_retiring_a_pair_deletes_its_leases(self):
        dataset, po, (r1, r2) = make_dataset("retire", resources=2)
        _, fms = make_collection("retire-fc", 1)
        settle_inputs()
        pair = ExtractTaskBuildProgress.objects.get(dataset_id=dataset.id, resource_ids=[r2.id])
        lease = make_lease(pair, [fms[0].id])
        r2.delete()
        settle_inputs()
        self.assertFalse(ExtractTaskLease.objects.filter(id=lease.id).exists())
        pair.refresh_from_db()
        self.assertFalse(pair.current)

    def test_inactive_inputs_park_pairs_rather_than_removing_them(self):
        dataset, po, resources = make_dataset("parked", resources=1, active=False)
        po.active = False
        po.save()
        settle_inputs()
        self.assertEqual(current_sets(dataset), {((resources[0].id,), po.id)})

    def test_a_grouped_resource_without_a_date_is_a_visible_configuration_error(self):
        dataset, po, resources = make_dataset("undated", resources=2, period="year")
        DatasetResource.objects.filter(id=resources[1].id).update(temporal=None)
        with self.assertLogs("analytics.sync", "ERROR"):
            stats = sync.sync_extract_work()
        self.assertEqual(stats["errors"], 1)
        s = state("dataset", dataset.id)
        self.assertNotEqual(s.generation, s.applied_generation)
        self.assertIn("no temporal value", s.last_error)
        self.assertGreater(s.retry_after, dj_timezone.now())
        # Fixing the input is itself a change, which clears the backoff.
        DatasetResource.objects.filter(id=resources[1].id).update(temporal=datetime(2020, 3, 1, tzinfo=UTC))
        settle_inputs()
        s = state("dataset", dataset.id)
        self.assertEqual(s.generation, s.applied_generation)
        self.assertIsNone(s.last_error)

    def test_grouped_non_global_datasets_are_supported(self):
        extent = Polygon(((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)))
        dataset, po, resources = make_dataset("grp-local", resources=3, period="year",
                                              is_global=False, extent=extent)
        settle_inputs()
        self.assertEqual(len(current_sets(dataset)), 1)
        self.assertTrue(CoverageProgress.objects.filter(dataset_id=dataset.id).exists())


class PublishTests(TestCase):
    def test_coverage_progress_follows_global_and_extent_changes(self):
        dataset, po, _ = make_dataset("cov", is_global=False,
                                      extent=Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))))
        settle_inputs()
        progress = CoverageProgress.objects.get(dataset_id=dataset.id)
        self.assertEqual(progress.covered_up_to_fm_id, 0)
        self.assertIsNotNone(progress.extent_hash)

        CoverageProgress.objects.filter(dataset_id=dataset.id).update(covered_up_to_fm_id=900)
        Dataset.objects.filter(id=dataset.id).update(
            spatial_extent=Polygon(((0, 0), (2, 0), (2, 2), (0, 2), (0, 0))))
        settle_inputs()
        progress.refresh_from_db()
        self.assertEqual(progress.covered_up_to_fm_id, 0)

        Dataset.objects.filter(id=dataset.id).update(is_global=True)
        settle_inputs()
        self.assertFalse(CoverageProgress.objects.filter(dataset_id=dataset.id).exists())

    def test_a_collection_change_rewinds_every_datasets_cursors_and_coverage(self):
        global_ds, _, _ = make_dataset("rw-global")
        paused_ds, _, _ = make_dataset("rw-paused", active=False)
        local_ds, _, _ = make_dataset("rw-local", is_global=False,
                                      extent=Polygon(((0, 0), (9, 0), (9, 9), (0, 9), (0, 0))))
        fc, fms = make_collection("rw-fc", 3)
        settle_inputs()
        ExtractTaskBuildProgress.objects.update(cursor_fm_id=10_000)
        CoverageProgress.objects.update(covered_up_to_fm_id=10_000)

        added = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(2, 2)))
        settle_inputs()
        for pair in ExtractTaskBuildProgress.objects.filter(current=True):
            self.assertEqual(pair.cursor_fm_id, added.id - 1, pair)
        self.assertEqual(
            CoverageProgress.objects.get(dataset_id=local_ds.id).covered_up_to_fm_id, added.id - 1,
        )

    def test_an_invalidating_dataset_change_retokens_its_leases_and_an_additive_one_does_not(self):
        dataset, po, (resource,) = make_dataset("tok")
        other, _, _ = make_dataset("tok-other")
        _, fms = make_collection("tok-fc", 1)
        settle_inputs()
        pair = ExtractTaskBuildProgress.objects.get(dataset_id=dataset.id)
        other_pair = ExtractTaskBuildProgress.objects.get(dataset_id=other.id)
        lease = make_lease(pair, [fms[0].id], attempts=2)
        untouched = make_lease(other_pair, [fms[0].id], attempts=2)

        DatasetResource.objects.create(dataset=dataset, name="tok-new", path="n.tif")
        settle_inputs()
        self.assertEqual(ExtractTaskLease.objects.get(id=lease.id).token, lease.token)

        Dataset.objects.filter(id=dataset.id).update(path="/data/tok-v2")
        settle_inputs()
        before, after = lease.token, ExtractTaskLease.objects.get(id=lease.id)
        self.assertNotEqual(after.token, before)
        self.assertLessEqual(after.leased_until, dj_timezone.now())
        self.assertEqual(after.attempts, 0)
        self.assertEqual(ExtractTaskLease.objects.get(id=untouched.id).token, untouched.token)

    def test_a_collection_publish_drops_deleted_members_and_keeps_the_rest(self):
        dataset, po, _ = make_dataset("members")
        fc, fms = make_collection("members-fc", 3)
        settle_inputs()
        pair = ExtractTaskBuildProgress.objects.get(dataset_id=dataset.id)
        lease = make_lease(pair, [fm.id for fm in fms])
        only = make_lease(pair, [fms[2].id])
        fms[2].geom.delete()  # cascades the feat_map row
        settle_inputs()
        lease.refresh_from_db()
        self.assertEqual(lease.fm_ids, [fms[0].id, fms[1].id])
        self.assertFalse(ExtractTaskLease.objects.filter(id=only.id).exists())


@override_settings(EXTRACT_RESET_CHUNK_SIZE=2)
class ResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset, cls.po, (cls.r1, cls.r2) = make_dataset("reset", resources=2)
        cls.other, cls.other_po, (cls.other_r,) = make_dataset("reset-other")
        cls.fc, cls.fms = make_collection("reset-fc", 3)
        cls.fc2, cls.fms2 = make_collection("reset-fc2", 1)
        settle_inputs()

    def make_done(self, dataset, po, resource, fm, **fields):
        task = ExtractTask.objects.create(
            dataset_id=dataset.id, resource_ids=[resource.id], fm=fm, po=po, status=1,
            attempts=2, error=None, complete_time=dj_timezone.now(),
            update_time=dj_timezone.now() - timedelta(hours=1), priority=1, **fields,
        )
        ExtractData.objects.create(extract_task=task, dataset_id=dataset.id, name="mean", float_value=1.0)
        return task

    def test_a_dataset_reset_covers_every_task_in_bounded_chunks(self):
        tasks = [
            self.make_done(self.dataset, self.po, r, fm, kwargs=kw)
            for r in (self.r1, self.r2) for fm in self.fms for kw in (None, {"k": 1})
        ]
        req = Request.objects.create(contact="a@b.c", status=-1, data={})
        RequestMap.objects.create(request=req, task=tasks[0], dataset_id=self.dataset.id)
        untouched = self.make_done(self.other, self.other_po, self.other_r, self.fms[0])
        stamp = ExtractTask.objects.get(id=tasks[0].id).update_time

        ExtractTaskBuildProgress.objects.filter(dataset_id=self.dataset.id).update(cursor_fm_id=10_000)

        Dataset.objects.filter(id=self.dataset.id).update(path="/data/moved")
        chunks = settle_inputs()
        # pairs, then 12 tasks at 2 per chunk (plus an empty final check), then
        # publish -- each its own transaction.
        self.assertGreaterEqual(chunks, 7)
        # Background work goes with its results; the request's task waits for
        # a worker, keeping its id, link and priority.
        task = ExtractTask.objects.get(dataset_id=self.dataset.id)
        self.assertEqual(task.id, tasks[0].id)
        self.assertEqual((task.status, task.attempts, task.error, task.complete_time), (0, 0, None, None))
        self.assertNotEqual(task.update_time, stamp)
        self.assertEqual(task.priority, 1)
        self.assertFalse(ExtractData.objects.filter(dataset_id=self.dataset.id).exists())
        self.assertTrue(RequestMap.objects.filter(request=req, task_id=tasks[0].id).exists())
        # Every pair starts over, so leases bring the deleted work back.
        self.assertEqual(
            set(ExtractTaskBuildProgress.objects.filter(dataset_id=self.dataset.id)
                .values_list("cursor_fm_id", flat=True)),
            {0},
        )
        untouched.refresh_from_db()
        self.assertEqual(untouched.status, 1)
        self.assertTrue(ExtractData.objects.filter(dataset_id=self.other.id).exists())

    def test_a_resource_change_resets_and_rewinds_only_its_own_sets(self):
        changed = [self.make_done(self.dataset, self.po, self.r1, fm) for fm in self.fms]
        kept = [self.make_done(self.dataset, self.po, self.r2, fm) for fm in self.fms]
        ExtractTaskBuildProgress.objects.filter(dataset_id=self.dataset.id).update(cursor_fm_id=10_000)
        DatasetResource.objects.filter(id=self.r1.id).update(path="r1-v2.tif")
        settle_inputs()
        self.assertFalse(ExtractTask.objects.filter(
            dataset_id=self.dataset.id, id__in=[t.id for t in changed]).exists())
        self.assertEqual(
            set(ExtractTask.objects.filter(id__in=[t.id for t in kept]).values_list("status", flat=True)), {1})
        cursors = {
            tuple(resource_ids): cursor
            for resource_ids, cursor in ExtractTaskBuildProgress.objects.filter(
                dataset_id=self.dataset.id, current=True).values_list("resource_ids", "cursor_fm_id")
        }
        self.assertEqual(cursors, {(self.r1.id,): 0, (self.r2.id,): 10_000})

    def test_tasks_naming_a_deleted_resource_fail_terminally(self):
        from django.conf import settings

        doomed = self.make_done(self.dataset, self.po, self.r2, self.fms[0])
        background = self.make_done(self.dataset, self.po, self.r2, self.fms[1])
        kept = self.make_done(self.dataset, self.po, self.r1, self.fms[0])
        req = Request.objects.create(contact="a@b.c", status=-1, data={})
        RequestMap.objects.create(request=req, task=doomed, dataset_id=self.dataset.id)
        # Deleting the resource by raw SQL leaves its tasks behind, as a
        # resource deleted outside the ORM would.
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM dataset_resources WHERE id = %s", [self.r2.id])
        settle_inputs()
        doomed.refresh_from_db()
        self.assertEqual(doomed.status, -1)
        self.assertEqual(doomed.attempts, settings.MAX_EXTRACT_TASK_ATTEMPTS)
        self.assertIn("no longer exists", doomed.error)
        self.assertFalse(ExtractTask.objects.filter(dataset_id=self.dataset.id, id=background.id).exists())
        # Only the deleted resource's tasks were touched.
        kept.refresh_from_db()
        self.assertEqual(kept.status, 1)

    def test_a_reshape_resets_only_that_features_tasks_in_every_dataset(self):
        neighbours = [self.make_done(self.dataset, self.po, self.r1, fm) for fm in (self.fms[0], self.fms[2])]
        reshaped = self.make_done(self.dataset, self.po, self.r1, self.fms[1])
        requested = self.make_done(self.other, self.other_po, self.other_r, self.fms[1])
        req = Request.objects.create(contact="a@b.c", status=-1, data={})
        RequestMap.objects.create(request=req, task=requested, dataset_id=self.other.id)
        theirs = self.make_done(self.dataset, self.po, self.r1, self.fms2[0])
        Feature.objects.filter(id=self.fms[1].geom_id).update(shape=Point(70, 70))
        settle_inputs()
        self.assertFalse(ExtractTask.objects.filter(dataset_id=self.dataset.id, id=reshaped.id).exists())
        requested.refresh_from_db()
        self.assertEqual(requested.status, 0)
        self.assertEqual(
            set(ExtractTask.objects.filter(id__in=[t.id for t in neighbours + [theirs]])
                .values_list("status", flat=True)),
            {1},
        )
        self.assertFalse(ExtractInvalidItem.objects.exists())

    def test_readers_and_readiness_ignore_results_until_the_reset_is_published(self):
        from analytics.management.commands.manage_user_requests import _check_request_tasks

        task = self.make_done(self.dataset, self.po, self.r1, self.fms[0])
        req = Request.objects.create(contact="a@b.c", status=-1, data={})
        RequestMap.objects.create(request=req, task=task, dataset_id=self.dataset.id)
        self.assertEqual(_check_request_tasks(req, dry_run=True)[0], 0)

        DatasetResource.objects.filter(id=self.r1.id).update(path="v2.tif")
        pending, completed, _ = _check_request_tasks(req, dry_run=True)
        self.assertEqual((pending, completed), (1, {}))

    def test_an_edit_mid_reset_restarts_the_phases_with_the_flags_accumulated(self):
        for fm in self.fms:
            self.make_done(self.dataset, self.po, self.r1, fm)
            self.make_done(self.dataset, self.po, self.r2, fm)
        DatasetResource.objects.filter(id=self.r1.id).update(path="first.tif")
        sync.sync_extract_work(max_chunks=1)  # one reset chunk
        s = state("dataset", self.dataset.id)
        self.assertEqual(s.checkpoint["phase"], "reset_items")
        self.assertNotEqual(s.generation, s.applied_generation)

        Dataset.objects.filter(id=self.dataset.id).update(is_global=False)
        s = state("dataset", self.dataset.id)
        self.assertEqual(s.checkpoint, {})
        self.assertTrue(s.reset_coverage and s.sync_pairs)
        self.assertTrue(ExtractInvalidItem.objects.filter(scope_id=self.dataset.id).exists())
        self.assertEqual(s.rewind_from, 0)

        settle_inputs()
        s = state("dataset", self.dataset.id)
        self.assertEqual(s.generation, s.applied_generation)
        self.assertFalse(s.reset_tasks or s.reset_coverage or s.sync_pairs)
        self.assertFalse(ExtractInvalidItem.objects.exists())
        # The first edit's tasks are gone; the extent change kept the rest.
        remaining = ExtractTask.objects.filter(dataset_id=self.dataset.id)
        self.assertEqual({tuple(t.resource_ids) for t in remaining}, {(self.r2.id,)})

    def test_a_scope_is_never_published_after_part_of_its_repair(self):
        for fm in self.fms:
            self.make_done(self.dataset, self.po, self.r1, fm)
        Dataset.objects.filter(id=self.dataset.id).update(path="/data/partial")
        for _ in range(3):
            sync.sync_extract_work(max_chunks=1)
            s = state("dataset", self.dataset.id)
            if s.generation == s.applied_generation:
                break
            self.assertTrue(s.reset_tasks)
        # Only once every task was reset does the scope publish.
        settle_inputs()
        self.assertFalse(ExtractTask.objects.filter(dataset_id=self.dataset.id, status=1).exists())


class RobustnessTests(TestCase):
    def test_a_failing_scope_is_backed_off_and_the_rest_continue(self):
        good, _, _ = make_dataset("good")
        bad, _, _ = make_dataset("bad")
        real = sync._phase_pairs

        def flaky(cursor, scope, checkpoint):
            if scope.object_id == bad.id:
                raise RuntimeError("disk on fire")
            return real(cursor, scope, checkpoint)

        with mock.patch.dict(sync._PHASES, {("dataset", "pairs"): flaky}), \
                self.assertLogs("analytics.sync", "ERROR"):
            sync.run_until_clean()
        self.assertEqual(state("dataset", good.id).generation, state("dataset", good.id).applied_generation)
        s = state("dataset", bad.id)
        self.assertIn("disk on fire", s.last_error)
        self.assertEqual(s.checkpoint["failures"], 1)
        self.assertGreater(s.retry_after, dj_timezone.now())

    def test_bootstrap_pending_datasets_are_left_to_initialization(self):
        dataset, _, _ = make_dataset("boot")
        ExtractInputState.objects.filter(kind="dataset", object_id=dataset.id).update(bootstrap_pending=True)
        settle_inputs()
        s = state("dataset", dataset.id)
        self.assertNotEqual(s.generation, s.applied_generation)
        self.assertFalse(ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id).exists())

    def test_round_robin_lets_a_small_scope_finish_beside_a_long_reset(self):
        dataset, po, (r,) = make_dataset("long")
        fc, fms = make_collection("long-fc", 6)
        settle_inputs()
        for fm in fms:
            ExtractTask.objects.create(dataset_id=dataset.id, resource_ids=[r.id], fm=fm, po=po, status=1)
        DatasetResource.objects.filter(id=r.id).update(path="long2.tif")
        small, _ = make_collection("small-fc", 1)
        with self.settings(EXTRACT_RESET_CHUNK_SIZE=1):
            sync.sync_extract_work(max_chunks=4)
        s = state("collection", small.id)
        self.assertEqual(s.generation, s.applied_generation)


class PartitionGateTests(TestCase):
    """A new dataset's pairs wait for its extract_tasks/extract_data partitions."""

    def _partitions(self, dataset):
        from datasets.partitions import missing_partitions

        return missing_partitions(dataset.id)

    def test_sync_creates_the_partitions_before_the_pairs(self):
        dataset, po, (r,) = make_dataset("parts")
        self.assertTrue(self._partitions(dataset))
        settle_inputs()
        self.assertEqual(self._partitions(dataset), [])
        self.assertEqual(current_sets(dataset), {((r.id,), po.id)})

    def test_a_partition_that_cannot_be_created_yet_defers_the_pairs(self):
        dataset, _, _ = make_dataset("busy")
        with mock.patch("datasets.partitions.ensure_dataset_partitions", return_value=[]):
            stats = sync.sync_extract_work()
        self.assertEqual(stats["errors"], 0)
        self.assertFalse(ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id).exists())
        s = state("dataset", dataset.id)
        self.assertNotEqual(s.generation, s.applied_generation)
        # Deferred, not failed: no backoff, so the next run tries again.
        self.assertIsNone(s.last_error)
        self.assertLessEqual(s.retry_after, dj_timezone.now())

        settle_inputs()
        self.assertEqual(self._partitions(dataset), [])
        self.assertTrue(ExtractTaskBuildProgress.objects.filter(dataset_id=dataset.id).exists())

    def test_rows_already_in_default_do_not_hold_the_pairs_back(self):
        dataset, po, (r,) = make_dataset("parked")
        with mock.patch("datasets.partitions.ensure_dataset_partitions", return_value=[]), \
                mock.patch("datasets.partitions.rows_parked_in_default",
                           return_value={"extract_tasks": 1, "extract_data": 0}):
            settle_inputs()
        self.assertEqual(current_sets(dataset), {((r.id,), po.id)})


class ConcurrentSyncTests(TransactionTestCase):
    def hold(self, sql, params, ready, release):
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    ready.set()
                    release.wait(10)
        finally:
            connections.close_all()

    def test_a_scope_another_sync_holds_is_skipped_not_waited_for(self):
        dataset, _, _ = make_dataset("held")
        ready, release = threading.Event(), threading.Event()
        holder = threading.Thread(target=self.hold, args=(
            "SELECT 1 FROM extract_input_state WHERE kind = 'dataset' AND object_id = %s FOR UPDATE",
            [dataset.id], ready, release,
        ))
        holder.start()
        ready.wait(5)
        try:
            stats = sync.sync_extract_work()
            self.assertGreaterEqual(stats["skipped"], 1)
            s = state("dataset", dataset.id)
            self.assertNotEqual(s.generation, s.applied_generation)
        finally:
            release.set()
            holder.join(10)
        settle_inputs()
        s = state("dataset", dataset.id)
        self.assertEqual(s.generation, s.applied_generation)

    def test_a_collection_publishes_while_a_dataset_is_busy(self):
        # A long dataset ingest or reset chunk holds its state; collections
        # (new boundaries, uploads) must still publish meanwhile.
        dataset, _, _ = make_dataset("share")
        fc, fms = make_collection("share-fc", 1)
        settle_inputs()
        added = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(3, 3)))
        ready, release = threading.Event(), threading.Event()
        holder = threading.Thread(target=self.hold, args=(
            "SELECT 1 FROM extract_input_state WHERE kind = 'dataset' AND object_id = %s FOR UPDATE",
            [dataset.id], ready, release,
        ))
        holder.start()
        ready.wait(5)
        try:
            sync.sync_extract_work()
            s = state("collection", fc.id)
            self.assertEqual(s.generation, s.applied_generation)
            pair = ExtractTaskBuildProgress.objects.get(dataset_id=dataset.id)
            self.assertLessEqual(pair.cursor_fm_id, added.id - 1)
        finally:
            release.set()
            holder.join(10)

    def test_a_lock_timeout_is_contention_not_a_failure(self):
        dataset, _, _ = make_dataset("contended")
        fc, _ = make_collection("contended-fc", 1)
        settle_inputs()
        FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(3, 3)))
        pair = ExtractTaskBuildProgress.objects.get(dataset_id=dataset.id)
        ready, release = threading.Event(), threading.Event()
        # A claim holding the pair past the publish's lock timeout.
        holder = threading.Thread(target=self.hold, args=(
            "SELECT 1 FROM extract_task_build_progress WHERE id = %s FOR UPDATE", [pair.id], ready, release,
        ))
        holder.start()
        ready.wait(5)
        try:
            with mock.patch.object(sync, "LOCK_TIMEOUT_MS", 100):
                stats = sync.sync_extract_work()
            self.assertEqual(stats["errors"], 0)
            s = state("collection", fc.id)
            self.assertNotEqual(s.generation, s.applied_generation)
            self.assertIsNone(s.last_error)
            self.assertNotIn("failures", s.checkpoint)
        finally:
            release.set()
            holder.join(10)
        settle_inputs()
        s = state("collection", fc.id)
        self.assertEqual(s.generation, s.applied_generation)

    def test_concurrent_syncs_do_not_block_or_double_apply(self):
        dataset, po, (r,) = make_dataset("race")
        fc, fms = make_collection("race-fc", 4)
        settle_inputs()
        for fm in fms:
            ExtractTask.objects.create(dataset_id=dataset.id, resource_ids=[r.id], fm=fm, po=po, status=1)
        DatasetResource.objects.filter(id=r.id).update(path="race2.tif")
        errors = []

        def run():
            try:
                with self.settings(EXTRACT_RESET_CHUNK_SIZE=1):
                    sync.run_until_clean(deadline_seconds=20)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertFalse(errors, errors)
        settle_inputs()
        s = state("dataset", dataset.id)
        self.assertEqual(s.generation, s.applied_generation)
        # Each background task was deleted exactly once, by whichever sync
        # reached it, and nothing was left half-reset.
        self.assertFalse(ExtractTask.objects.filter(dataset_id=dataset.id).exists())


class MarkTests(TestCase):
    def test_commands_record_the_same_durable_changes_as_triggers(self):
        dataset, _, _ = make_dataset("cmd")
        settle_inputs()
        with self.captureOnCommitCallbacks(execute=False):
            mark("dataset", [dataset.id], rewind_from=5, reset_tasks=True)
        s = state("dataset", dataset.id)
        self.assertEqual((s.rewind_from, s.reset_tasks), (5, True))
