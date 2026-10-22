"""Change capture: the triggers that record input changes in extract_input_state.

Every write path (ORM saves, bulk writes, raw SQL) must be captured, in the
same transaction as the change, and writes that change nothing an
extraction reads must not be.
"""

import threading
from unittest import mock

from django.contrib.gis.geos import Point, Polygon
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from analytics.models import ExtractInputState, ExtractInvalidItem, ProcessingOption
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from datasets.models import Dataset, DatasetResource, Mapping
from features.models import FeatMap, Feature, FeatureCollection


def state(kind, object_id):
    return ExtractInputState.objects.filter(kind=kind, object_id=object_id).first()


def items(kind, object_id):
    return set(
        ExtractInvalidItem.objects.filter(scope_kind=kind, scope_id=object_id)
        .values_list("item_kind", "item_id")
    )


class CaptureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset, cls.po, cls.resources = make_dataset("cap", resources=2)
        cls.fc, cls.fms = make_collection("cap-fc", 3)
        settle_inputs()

    def assertClean(self, kind, object_id):
        s = state(kind, object_id)
        self.assertIsNotNone(s, f"{kind} {object_id} has no state")
        self.assertEqual(s.generation, s.applied_generation, f"{kind} {object_id} is dirty: {s}")

    def test_settled_inputs_are_clean(self):
        self.assertClean("dataset", self.dataset.id)
        self.assertClean("collection", self.fc.id)

    def test_new_dataset_is_dirty_for_pair_sync_with_a_full_rewind(self):
        d = Dataset.objects.create(name="new", path="/data/new", type="raster")
        s = state("dataset", d.id)
        self.assertNotEqual(s.generation, s.applied_generation)
        self.assertTrue(s.sync_pairs)
        self.assertEqual(s.rewind_from, 0)
        self.assertFalse(s.reset_tasks)

    def test_new_collection_gets_a_clean_permanent_state(self):
        fc = FeatureCollection.objects.create(name="empty", path="/data/empty")
        self.assertClean("collection", fc.id)

    def test_feature_insert_rewinds_its_collection_below_it(self):
        before = state("collection", self.fc.id)
        fm = FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(5, 5)))
        s = state("collection", self.fc.id)
        self.assertEqual(s.generation, before.generation + 1)
        self.assertEqual(s.rewind_from, fm.id - 1)
        self.assertFalse(s.reset_tasks)
        # An addition invalidates nothing: work in flight is not fenced.
        self.assertEqual(s.epoch, before.epoch)

    def test_uploads_record_nothing(self):
        upload = FeatureCollection.objects.create(name="cap-up", path="/data/cap-up", is_user_upload=True)
        before = state("collection", upload.id)
        fm = FeatMap.objects.create(fc=upload, geom=Feature.objects.create(shape=Point(5, 5)))
        fm.delete()
        self.assertEqual(state("collection", upload.id).generation, before.generation)

    def test_bulk_and_raw_inserts_are_captured_once_per_statement(self):
        before = state("collection", self.fc.id).generation
        features = Feature.objects.bulk_create([Feature(shape=Point(i, 9)) for i in range(5)])
        created = FeatMap.objects.bulk_create([FeatMap(fc=self.fc, geom=f) for f in features])
        s = state("collection", self.fc.id)
        self.assertEqual(s.generation, before + 1)
        self.assertEqual(s.rewind_from, min(fm.id for fm in created) - 1)

        geom = Feature.objects.create(shape=Point(7, 7))
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO feat_map (fc_id, geom_id) VALUES (%s, %s) RETURNING id",
                [self.fc.id, geom.id],
            )
        self.assertEqual(state("collection", self.fc.id).generation, before + 2)

    def test_the_minimum_rewind_is_kept(self):
        settle_inputs()
        low = FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(1, 9)))
        FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(2, 9)))
        self.assertEqual(state("collection", self.fc.id).rewind_from, low.id - 1)

    def test_a_rolled_back_change_records_nothing(self):
        before = state("collection", self.fc.id).generation
        try:
            with transaction.atomic():
                FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(3, 3)))
                raise RuntimeError("roll back")
        except RuntimeError:
            pass
        self.assertEqual(state("collection", self.fc.id).generation, before)

    def test_display_only_and_same_value_writes_mark_nothing(self):
        d_before = state("dataset", self.dataset.id).generation
        c_before = state("collection", self.fc.id).generation
        Dataset.objects.filter(id=self.dataset.id).update(title="A new title", citation="x")
        self.dataset.refresh_from_db()
        self.dataset.save()  # rewrites every column with the same values
        FeatureCollection.objects.filter(id=self.fc.id).update(title="Renamed")
        FeatMap.objects.filter(id=self.fms[0].id).update(name="Renamed", attr={"a": 1})
        geom = self.fms[0].geom
        geom.refresh_from_db()
        geom.save()
        DatasetResource.objects.filter(id=self.resources[0].id).update(label="2020")
        self.assertEqual(state("dataset", self.dataset.id).generation, d_before)
        self.assertEqual(state("collection", self.fc.id).generation, c_before)

    def test_dataset_wide_inputs_reset_the_whole_dataset(self):
        cases = [
            lambda: Dataset.objects.filter(id=self.dataset.id).update(path="/data/elsewhere"),
            lambda: Dataset.objects.filter(id=self.dataset.id).update(mapped=True),
        ]
        for change in cases:
            with self.subTest(change=change):
                settle_inputs()
                before = state("dataset", self.dataset.id).epoch
                change()
                s = state("dataset", self.dataset.id)
                self.assertNotEqual(s.generation, s.applied_generation)
                self.assertTrue(s.reset_tasks)
                self.assertTrue(s.sync_pairs)
                self.assertEqual(s.epoch, before + 1)

    def test_a_resource_or_option_change_resets_only_its_own_tasks(self):
        r0, r1 = self.resources
        cases = [
            (lambda: DatasetResource.objects.filter(id=r0.id).update(path="moved.tif"), ("resource", r0.id)),
            (lambda: ProcessingOption.objects.filter(id=self.po.id).update(kwargs={"band": 2}),
             ("option", self.po.id)),
            (lambda: ProcessingOption.objects.filter(id=self.po.id).update(function="rasterstats_default_max"),
             ("option", self.po.id)),
            (lambda: DatasetResource.objects.filter(id=r1.id).delete(), ("resource", r1.id)),
        ]
        for change, item in cases:
            with self.subTest(item=item):
                settle_inputs()
                before = state("dataset", self.dataset.id).epoch
                change()
                s = state("dataset", self.dataset.id)
                self.assertNotEqual(s.generation, s.applied_generation)
                self.assertFalse(s.reset_tasks)
                self.assertEqual(items("dataset", self.dataset.id), {item})
                self.assertEqual(s.epoch, before + 1)

    def test_membership_and_activity_changes_sync_pairs_without_a_reset(self):
        cases = [
            lambda: DatasetResource.objects.create(dataset=self.dataset, name="cap-r9", path="r9.tif"),
            lambda: DatasetResource.objects.filter(id=self.resources[0].id).update(
                temporal="2031-01-01T00:00:00Z"),
            lambda: Dataset.objects.filter(id=self.dataset.id).update(active=False),
            lambda: Dataset.objects.filter(id=self.dataset.id).update(task_group_period="year"),
            lambda: ProcessingOption.objects.filter(id=self.po.id).update(active=False),
            lambda: ProcessingOption.objects.create(
                dataset=self.dataset, short_name="max", function="rasterstats_default_max"),
        ]
        for change in cases:
            with self.subTest(change=change):
                settle_inputs()
                before = state("dataset", self.dataset.id).epoch
                change()
                s = state("dataset", self.dataset.id)
                self.assertNotEqual(s.generation, s.applied_generation)
                self.assertTrue(s.sync_pairs)
                self.assertFalse(s.reset_tasks)
                self.assertEqual(s.epoch, before)

    def test_extent_and_global_changes_reset_coverage_not_results(self):
        for change in (
            lambda: Dataset.objects.filter(id=self.dataset.id).update(
                spatial_extent=Polygon(((0, 0), (5, 0), (5, 5), (0, 5), (0, 0)))),
            lambda: Dataset.objects.filter(id=self.dataset.id).update(is_global=False),
        ):
            with self.subTest(change=change):
                settle_inputs()
                change()
                s = state("dataset", self.dataset.id)
                self.assertTrue(s.reset_coverage)
                self.assertFalse(s.reset_tasks)
                self.assertEqual(s.rewind_from, 0)

    def test_category_maps_only_matter_for_mapped_datasets(self):
        before = state("dataset", self.dataset.id).generation
        Mapping.objects.create(dataset=self.dataset, map_name="water", map_val=1)
        self.assertEqual(state("dataset", self.dataset.id).generation, before)

        Dataset.objects.filter(id=self.dataset.id).update(mapped=True)
        settle_inputs()
        Mapping.objects.filter(dataset=self.dataset).update(map_name="lake")
        s = state("dataset", self.dataset.id)
        self.assertTrue(s.reset_tasks)

    def test_a_shape_change_resets_every_referencing_collection_once(self):
        other = FeatureCollection.objects.create(name="cap-other", path="/data/cap-other")
        shared = self.fms[1].geom
        mirror = FeatMap.objects.create(fc=other, geom=shared)
        settle_inputs()
        before = state("collection", self.fc.id).generation

        Feature.objects.filter(id=shared.id).update(shape=Point(42, 42))

        for fc_id, fm in ((self.fc.id, self.fms[1]), (other.id, mirror)):
            s = state("collection", fc_id)
            # Only the features using the geometry are reset; its coverage
            # was deleted by the trigger itself.
            self.assertEqual(items("collection", fc_id), {("feature", fm.id)})
            self.assertFalse(s.reset_tasks or s.reset_coverage)
            self.assertEqual(s.rewind_from, fm.id - 1)
        self.assertEqual(state("collection", self.fc.id).generation, before + 1)

    def test_moving_a_feature_fences_both_owners_and_rescans_it(self):
        other = FeatureCollection.objects.create(name="cap-dest", path="/data/cap-dest")
        settle_inputs()
        epochs = {fc: state("collection", fc).epoch for fc in (self.fc.id, other.id)}
        FeatMap.objects.filter(id=self.fms[2].id).update(fc=other)
        for fc_id in (self.fc.id, other.id):
            self.assertEqual(state("collection", fc_id).epoch, epochs[fc_id] + 1)
            # Same geometry, so its results stay valid.
            self.assertEqual(items("collection", fc_id), set())
        self.assertEqual(state("collection", other.id).rewind_from, self.fms[2].id - 1)

    def test_repointing_a_feature_resets_its_tasks(self):
        settle_inputs()
        FeatMap.objects.filter(id=self.fms[2].id).update(geom=Feature.objects.create(shape=Point(7, 7)))
        self.assertEqual(items("collection", self.fc.id), {("feature", self.fms[2].id)})
        self.assertEqual(state("collection", self.fc.id).rewind_from, self.fms[2].id - 1)

    def test_eligibility_changes_rewind_from_the_collections_lowest_feature(self):
        FeatureCollection.objects.filter(id=self.fc.id).update(active=False)
        FeatureCollection.objects.filter(id=self.fc.id).update(active=True)
        s = state("collection", self.fc.id)
        self.assertNotEqual(s.generation, s.applied_generation)
        self.assertEqual(s.rewind_from, min(fm.id for fm in self.fms) - 1)
        self.assertFalse(s.reset_tasks)

    def test_deletions_leave_tombstones_and_rewinds(self):
        doomed_fc, doomed_fms = make_collection("cap-doomed", 2)
        doomed_ds, _, _ = make_dataset("cap-doomed-ds")
        settle_inputs()
        fc_id, ds_id = doomed_fc.id, doomed_ds.id  # delete() clears pk
        doomed_fc.delete()  # cascades feat_map rows (and their features)
        doomed_ds.delete()
        fc_state = state("collection", fc_id)
        self.assertIsNotNone(fc_state)
        self.assertNotEqual(fc_state.generation, fc_state.applied_generation)
        self.assertEqual(fc_state.rewind_from, doomed_fms[0].id - 1)
        ds_state = state("dataset", ds_id)
        self.assertIsNotNone(ds_state)
        self.assertTrue(ds_state.reset_tasks)

        settle_inputs()
        self.assertIsNone(state("collection", fc_id))
        self.assertIsNone(state("dataset", ds_id))

    def test_a_new_change_clears_errors_and_backoff(self):
        ExtractInputState.objects.filter(kind="collection", object_id=self.fc.id).update(
            last_error="boom", retry_after="2999-01-01T00:00:00Z",
            checkpoint={"generation": 1, "phase": "reset_tasks"},
        )
        FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(8, 8)))
        s = state("collection", self.fc.id)
        self.assertIsNone(s.last_error)
        self.assertEqual(s.checkpoint, {})
        self.assertLess(s.retry_after.year, 2999)


class WakeTests(TestCase):
    def test_one_wake_per_transaction_however_many_changes(self):
        with mock.patch("analytics.tasks.maintenance.sync_extract_work") as task:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    make_dataset("wake-a", resources=3)
                    make_dataset("wake-b", resources=3)
                    make_collection("wake-fc", 20)
        task.apply_async.assert_called_once_with(retry=False)

    def test_features_alone_do_not_dispatch_per_feature(self):
        fc = FeatureCollection.objects.create(name="wake-quiet", path="/data/wake-quiet")
        with mock.patch("analytics.tasks.maintenance.sync_extract_work") as task:
            with self.captureOnCommitCallbacks(execute=True):
                for i in range(10):
                    FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(i, i)))
        task.apply_async.assert_not_called()


class ShapeEditLockOrderTests(TransactionTestCase):
    """A geometry edit and a concurrent attachment of the same feature.

    The attachment's trigger takes FOR SHARE on the feature, which conflicts
    with the edit's exclusive row lock: whichever commits second sees the
    other. Without it the edit could miss the new feat_map row (its join
    snapshot predates it) and the new collection would be computed from the
    old shape with nothing to reset it.
    """

    def test_an_attachment_waits_for_a_shape_edit_and_the_edit_is_not_missed(self):
        fc, (fm,) = make_collection("lock-a", 1)
        late = FeatureCollection.objects.create(name="lock-b", path="/data/lock-b")
        settle_inputs()
        feature = fm.geom
        edited = threading.Event()
        attached = threading.Event()
        errors = []

        def attach():
            try:
                edited.wait(5)
                FeatMap.objects.create(fc=late, geom=feature)
                attached.set()
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)
            finally:
                connections.close_all()

        thread = threading.Thread(target=attach)
        thread.start()
        with transaction.atomic():
            Feature.objects.filter(id=feature.id).update(shape=Point(50, 50))
            edited.set()
            # The attachment blocks on the feature's row lock until we commit.
            self.assertFalse(attached.wait(0.5))
        thread.join(10)
        self.assertFalse(errors, errors)
        self.assertTrue(attached.is_set())
        # The attachment committed after the edit, so its collection saw the
        # new shape; it is marked by its own insert.
        s = state("collection", late.id)
        self.assertNotEqual(s.generation, s.applied_generation)

    def test_an_edit_after_an_attachment_finds_the_new_collection(self):
        fc, (fm,) = make_collection("lock-c", 1)
        late = FeatureCollection.objects.create(name="lock-d", path="/data/lock-d")
        settle_inputs()
        feature = fm.geom
        attached = threading.Event()
        release = threading.Event()
        errors = []

        def attach():
            try:
                with transaction.atomic():
                    FeatMap.objects.create(fc=late, geom=feature)
                    attached.set()
                    release.wait(5)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connections.close_all()

        thread = threading.Thread(target=attach)
        thread.start()
        attached.wait(5)

        edit_done = threading.Event()

        def edit():
            try:
                Feature.objects.filter(id=feature.id).update(shape=Point(60, 60))
                edit_done.set()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connections.close_all()

        editor = threading.Thread(target=edit)
        editor.start()
        # The edit waits for the uncommitted attachment's share lock.
        self.assertFalse(edit_done.wait(0.5))
        release.set()
        thread.join(10)
        editor.join(10)
        self.assertFalse(errors, errors)
        # Its fresh snapshot found the attachment and logged it for a reset too.
        attached_fm = FeatMap.objects.get(fc=late)
        self.assertEqual(items("collection", late.id), {("feature", attached_fm.id)})
        self.assertEqual(items("collection", fc.id), {("feature", fm.id)})
