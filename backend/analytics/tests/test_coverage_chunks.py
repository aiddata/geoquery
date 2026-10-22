"""Coverage watermarks advanced by worker slots (analytics.coverage)."""

import threading

from django.contrib.gis.geos import Point, Polygon
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from analytics.coverage import barrier_for, run_coverage_chunk, valid_coverage
from analytics.models import Coverage, CoverageProgress
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from datasets.models import Dataset
from features.models import FeatMap, Feature, FeatureCollection

# Unit squares 0..4 lie inside this extent; 5 and up lie outside.
EXTENT = Polygon(((0, 0), (5, 0), (5, 1), (0, 1), (0, 0)))


def statuses(dataset):
    return dict(Coverage.objects.filter(dataset=dataset).values_list("geom_id", "status"))


def watermark(dataset):
    return CoverageProgress.objects.get(dataset_id=dataset.id).covered_up_to_fm_id


def drain():
    while run_coverage_chunk() is not None:
        pass


class CoverageChunkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset, _, _ = make_dataset("cov", is_global=False, extent=EXTENT)
        cls.fc, cls.fms = make_collection("cov-fc", 8)
        settle_inputs()

    def test_each_geometry_is_tested_against_the_extent(self):
        drain()
        expected = {fm.geom_id: (1 if i < 5 else 0) for i, fm in enumerate(self.fms)}
        self.assertEqual(statuses(self.dataset), expected)
        self.assertEqual(watermark(self.dataset), self.fms[-1].id)

    @override_settings(EXTRACT_COVERAGE_CHUNK_SIZE=3)
    def test_a_chunk_examines_a_bounded_window(self):
        self.assertEqual(run_coverage_chunk(), 3)
        self.assertEqual(watermark(self.dataset), self.fms[2].id)
        self.assertEqual(len(statuses(self.dataset)), 3)

    def test_global_and_clean_but_finished_datasets_need_nothing(self):
        drain()
        self.assertIsNone(run_coverage_chunk())
        global_ds, _, _ = make_dataset("cov-global")
        settle_inputs()
        self.assertFalse(CoverageProgress.objects.filter(dataset_id=global_ds.id).exists())

    def test_uploads_are_never_covered_but_inactive_collections_are(self):
        upload, (up_fm,) = make_collection("cov-upload", 1, upload=True)
        inactive, (off_fm,) = make_collection("cov-off", 1, active=False)
        settle_inputs()
        drain()
        covered = statuses(self.dataset)
        self.assertNotIn(up_fm.geom_id, covered)
        self.assertIn(off_fm.geom_id, covered)
        self.assertEqual(watermark(self.dataset), max(up_fm.id, off_fm.id))

    def test_a_dirty_dataset_is_not_covered(self):
        Dataset.objects.filter(id=self.dataset.id).update(
            spatial_extent=Polygon(((0, 0), (2, 0), (2, 1), (0, 1), (0, 0))))
        self.assertIsNone(run_coverage_chunk())

    def test_a_collection_being_reset_is_skipped_only_above_its_durable_rewind(self):
        late = FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(
            shape=Polygon(((1, 0), (2, 0), (2, 1), (1, 1), (1, 0)))))
        # (epoch, unavailable, rewind_from): a collection being reset as a
        # whole may be passed only above its rewind; one a writer holds
        # (absent) not at all; one with only additions pending freely.
        resetting = {self.fc.id: (1, True, late.id - 1)}
        self.assertEqual(barrier_for([(self.fms[0].id, self.fc.id)], resetting), self.fms[0].id)
        self.assertIsNone(barrier_for([(late.id, self.fc.id)], resetting))
        self.assertEqual(barrier_for([(late.id, self.fc.id)], {}), late.id)
        self.assertIsNone(barrier_for([(self.fms[0].id, self.fc.id)], {self.fc.id: (1, False, late.id - 1)}))

    def test_new_features_are_covered_before_their_collection_publishes(self):
        drain()
        other, fms = make_collection("cov-late", 2)  # dirty, with additions only
        late = FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(
            shape=Polygon(((1, 0), (2, 0), (2, 1), (1, 1), (1, 0)))))
        drain()
        for fm in (*fms, late):
            self.assertIn(fm.geom_id, statuses(self.dataset))
        self.assertEqual(watermark(self.dataset), late.id)
        settle_inputs()  # the publish rewinds; the rescan finds them covered
        self.assertEqual(watermark(self.dataset), fms[0].id - 1)
        drain()
        self.assertEqual(watermark(self.dataset), late.id)

    def test_an_extent_change_replaces_the_coverage(self):
        drain()
        Dataset.objects.filter(id=self.dataset.id).update(
            spatial_extent=Polygon(((5, 0), (8, 0), (8, 1), (5, 1), (5, 0))))
        # Old rows are not served while they are being invalidated.
        self.assertFalse(valid_coverage().filter(dataset=self.dataset).exists())
        settle_inputs()
        self.assertEqual(statuses(self.dataset), {})
        drain()
        expected = {fm.geom_id: (1 if 5 <= i < 8 else 0) for i, fm in enumerate(self.fms)}
        self.assertEqual(statuses(self.dataset), expected)

    def test_a_reshaped_geometry_is_recovered(self):
        drain()
        moved = self.fms[0].geom
        Feature.objects.filter(id=moved.id).update(
            shape=Polygon(((20, 0), (21, 0), (21, 1), (20, 1), (20, 0))))
        self.assertNotIn(moved.id, set(valid_coverage().values_list("geom_id", flat=True)))
        settle_inputs()
        drain()
        self.assertEqual(statuses(self.dataset)[moved.id], 0)


    def test_a_reshape_resets_only_that_geometry(self):
        # Only the reshaped feature is rewound, so nothing below it, in its
        # own collection or one sharing a geometry with it, may lose coverage.
        other, _ = make_collection("cov-share", 0)
        FeatMap.objects.create(fc=other, geom=self.fms[0].geom)
        settle_inputs()
        drain()
        before = statuses(self.dataset)
        moved = self.fms[3].geom
        Feature.objects.filter(id=moved.id).update(
            shape=Polygon(((20, 0), (21, 0), (21, 1), (20, 1), (20, 0))))
        self.assertNotIn(moved.id, statuses(self.dataset))
        settle_inputs()
        drain()
        self.assertEqual(statuses(self.dataset), {**before, moved.id: 0})

    def test_reshaping_an_unattached_geometry_drops_its_coverage(self):
        drain()
        geom = self.fms[1].geom
        FeatMap.objects.filter(id=self.fms[1].id).delete()
        Feature.objects.filter(id=geom.id).update(
            shape=Polygon(((20, 0), (21, 0), (21, 1), (20, 1), (20, 0))))
        self.assertNotIn(geom.id, statuses(self.dataset))

    def test_pointing_a_feature_at_another_geometry_covers_the_new_one(self):
        drain()
        old = self.fms[2].geom_id
        new = Feature.objects.create(shape=Polygon(((6, 0), (7, 0), (7, 1), (6, 1), (6, 0))))
        FeatMap.objects.filter(id=self.fms[2].id).update(geom=new)
        settle_inputs()
        drain()
        self.assertEqual(statuses(self.dataset)[old], 1)
        self.assertEqual(statuses(self.dataset)[new.id], 0)


class CoverageBarrierTests(TransactionTestCase):
    def test_a_collection_held_by_a_writer_stops_the_watermark_before_it(self):
        dataset, _, _ = make_dataset("bar", is_global=False, extent=EXTENT)
        first, first_fms = make_collection("bar-a", 2)
        held, held_fms = make_collection("bar-b", 2)
        settle_inputs()
        ready, release = threading.Event(), threading.Event()

        def hold():
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT 1 FROM extract_input_state "
                            "WHERE kind = 'collection' AND object_id = %s FOR UPDATE",
                            [held.id],
                        )
                        ready.set()
                        release.wait(10)
            finally:
                connections.close_all()

        thread = threading.Thread(target=hold)
        thread.start()
        ready.wait(5)
        try:
            drain()
            self.assertEqual(watermark(dataset), held_fms[0].id - 1)
            self.assertEqual(set(statuses(dataset)), {fm.geom_id for fm in first_fms})
        finally:
            release.set()
            thread.join(10)
        drain()
        self.assertEqual(watermark(dataset), held_fms[-1].id)
