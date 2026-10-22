"""Features committed after a cursor has passed their id.

feat_map ids are allocated before their transaction commits, so id 101 can
become visible after 102 has been scanned, leased and completed. Nothing
compares counts or maximum ids to notice: the insert's own trigger records a
durable rewind below 101, and publishing it brings every cursor and
watermark back.

Inserts into one collection serialize on its input-state row (each insert's
trigger updates it), so the interleaving needs two collections: 101 in one,
102 in another.
"""

import threading
import time
from unittest import mock

from django.contrib.gis.geos import Point, Polygon
from django.db import connection, connections, transaction
from django.test import TransactionTestCase

from analytics import coverage
from analytics.coverage import run_coverage_chunk
from analytics.models import Coverage, CoverageProgress, ExtractTask, ExtractTaskBuildProgress
from analytics.tasks import leases
from analytics.tasks.leases import claim_lease, run_lease
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from features.models import FeatMap, Feature, FeatureCollection

EXTENT = Polygon(((-100, -100), (100, -100), (100, 100), (-100, 100), (-100, -100)))


def value(geometry, path, **kwargs):
    return [(kwargs["name"], 1.0)]


class LateCommitCase(TransactionTestCase):
    """Patched processors and helpers to hold a feature uncommitted."""

    def setUp(self):
        for target, value_ in (("get_func", value), ("get_batch_func", None)):
            patcher = mock.patch.object(leases, target, return_value=value_)
            patcher.start()
            self.addCleanup(patcher.stop)

    def drain_leases(self):
        while (lease := claim_lease()) is not None:
            self.assertEqual(run_lease(lease), "completed")

    def drain_coverage(self):
        while run_coverage_chunk() is not None:
            pass

    def hold_insert(self, fc, allocated, release, done, *, new_collection=None):
        """Insert a feature in its own transaction and keep it uncommitted."""
        try:
            with transaction.atomic():
                target = fc
                if new_collection is not None:
                    target = FeatureCollection.objects.create(
                        name=new_collection, path=f"/data/{new_collection}", active=True)
                fm = FeatMap.objects.create(fc=target, geom=Feature.objects.create(shape=Point(0.5, 0.5)))
                allocated.append(fm.id)
                done.set()
                release.wait(10)
        finally:
            connections.close_all()

    def interleave(self, fc, other, **kwargs):
        """Allocate X in ``fc``, commit Y > X in ``other`` and process past it, then commit X.

        Existing work is processed first. While X is uncommitted its
        trigger holds ``fc``'s state row, and a scan never passes committed
        features of a collection a writer holds; X can only be skipped when
        nothing of ``fc`` is committed in the window, which is the case the
        durable rewind exists for.
        """
        settle_inputs()
        self.drain_coverage()
        self.drain_leases()
        allocated, release, done = [], threading.Event(), threading.Event()
        holder = threading.Thread(target=self.hold_insert, args=(fc, allocated, release, done), kwargs=kwargs)
        holder.start()
        done.wait(5)
        later = FeatMap.objects.create(fc=other, geom=Feature.objects.create(shape=Point(1.5, 1.5)))
        self.assertGreater(later.id, allocated[0])
        settle_inputs()
        self.drain_coverage()
        self.drain_leases()
        release.set()
        holder.join(10)
        return allocated[0], later.id


class LateCommitTests(LateCommitCase):
    def test_a_pair_cursor_comes_back_for_a_late_feature(self):
        dataset, _, _ = make_dataset("late")
        fc, _ = make_collection("late-fc", 2)
        other, _ = make_collection("late-other", 0)
        settle_inputs()
        late, later = self.interleave(fc, other)
        pair = ExtractTaskBuildProgress.objects.get(dataset_id=dataset.id)
        self.assertGreaterEqual(pair.cursor_fm_id, later)
        self.assertFalse(ExtractTask.objects.filter(dataset_id=dataset.id, fm_id=late).exists())

        settle_inputs()
        pair.refresh_from_db()
        self.assertEqual(pair.cursor_fm_id, late - 1)
        self.drain_leases()
        self.assertEqual(
            ExtractTask.objects.filter(dataset_id=dataset.id, fm_id=late).values_list("status", flat=True).get(),
            1,
        )
        self.assertEqual(ExtractTask.objects.filter(dataset_id=dataset.id).count(), 4)

    def test_a_scan_does_not_pass_a_collection_a_writer_holds(self):
        dataset, _, _ = make_dataset("held-scan")
        fc, fms = make_collection("held-scan-fc", 2)
        settle_inputs()
        allocated, release, done = [], threading.Event(), threading.Event()
        holder = threading.Thread(target=self.hold_insert, args=(fc, allocated, release, done))
        holder.start()
        done.wait(5)
        try:
            self.assertIsNone(claim_lease())
            pair = ExtractTaskBuildProgress.objects.get(dataset_id=dataset.id)
            self.assertLess(pair.cursor_fm_id, fms[0].id)
        finally:
            release.set()
            holder.join(10)

    def test_inserts_into_one_collection_serialize_on_its_state(self):
        # Why the interleaving above needs two collections.
        make_dataset("serial")
        fc, _ = make_collection("serial-fc", 1)
        settle_inputs()
        allocated, release, done = [], threading.Event(), threading.Event()
        holder = threading.Thread(target=self.hold_insert, args=(fc, allocated, release, done))
        holder.start()
        done.wait(5)
        inserted = threading.Event()

        def second():
            try:
                FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(3, 3)))
                inserted.set()
            finally:
                connections.close_all()

        follower = threading.Thread(target=second)
        follower.start()
        self.assertFalse(inserted.wait(0.5))
        release.set()
        holder.join(10)
        follower.join(10)
        self.assertTrue(inserted.is_set())

    def test_a_coverage_watermark_comes_back_for_a_late_feature(self):
        dataset, _, _ = make_dataset("late-cov", is_global=False, extent=EXTENT)
        fc, _ = make_collection("late-cov-fc", 2)
        other, _ = make_collection("late-cov-other", 0)
        settle_inputs()
        late, later = self.interleave(fc, other)
        late_geom = FeatMap.objects.get(id=late).geom_id
        self.assertFalse(Coverage.objects.filter(dataset=dataset, geom_id=late_geom).exists())

        settle_inputs()
        self.assertEqual(CoverageProgress.objects.get(dataset=dataset).covered_up_to_fm_id, late - 1)
        # (The watermark rewinds to the late feature, not to 0.)
        self.drain_coverage()
        self.assertEqual(Coverage.objects.get(dataset=dataset, geom_id=late_geom).status, 1)
        self.drain_leases()
        self.assertTrue(ExtractTask.objects.filter(dataset_id=dataset.id, fm_id=late, status=1).exists())

    def test_a_late_new_collection_is_found(self):
        dataset, _, _ = make_dataset("late-new")
        fc, _ = make_collection("late-new-fc", 1)
        settle_inputs()
        late, _ = self.interleave(fc, fc, new_collection="late-new-other")
        settle_inputs()
        self.drain_leases()
        self.assertTrue(ExtractTask.objects.filter(dataset_id=dataset.id, fm_id=late, status=1).exists())

    def test_replacing_every_feature_with_the_same_count_is_recomputed(self):
        dataset, _, _ = make_dataset("replace")
        fc, fms = make_collection("replace-fc", 3)
        settle_inputs()
        self.drain_leases()
        geoms = [fm.geom_id for fm in fms]
        Feature.objects.filter(id__in=geoms).delete()  # takes the feat_map rows and their tasks
        _, fresh = make_collection("replace-tmp", 0)
        replacements = [
            FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(i, i)))
            for i in range(3)
        ]
        self.assertEqual(FeatMap.objects.filter(fc=fc).count(), 3)
        settle_inputs()
        self.drain_leases()
        self.assertEqual(
            set(ExtractTask.objects.filter(dataset_id=dataset.id, status=1).values_list("fm_id", flat=True)),
            {fm.id for fm in replacements},
        )

    def test_a_lost_wake_message_loses_no_work(self):
        dataset, _, _ = make_dataset("unwoken")
        with mock.patch("analytics.changes._send_wake"):
            fc, fms = make_collection("unwoken-fc", 2)
        # Beat's sync finds the change in the durable queue regardless.
        settle_inputs()
        self.drain_leases()
        self.assertEqual(ExtractTask.objects.filter(dataset_id=dataset.id, status=1).count(), 2)


class PublishDuringScanTests(LateCommitCase):
    """A collection's rewind published while a scan is between its reads and its commit.

    The scan has read its window when a late feature's collection commits and
    is published. The publish must wait for the scan and rewind what it
    leaves; it must not see the cursor still below its rewind and do nothing
    while the scan moves it past the feature.
    """

    def publish_while_paused(self, module, work, between):
        """Run ``work`` until its first ``module.barrier_for``, then ``between``,
        then publish everything dirty while it is paused, then let it finish."""
        paused, go = threading.Event(), threading.Event()
        real, results = module.barrier_for, []

        def pausing(*args):
            if not paused.is_set():
                paused.set()
                go.wait(10)
            return real(*args)

        def run(target, out):
            try:
                out.append(target())
            except Exception as exc:  # pragma: no cover
                out.append(exc)
            finally:
                connections.close_all()

        published = []
        with mock.patch.object(module, "barrier_for", pausing):
            scan = threading.Thread(target=run, args=(work, results))
            scan.start()
            self.assertTrue(paused.wait(10))
            between()
            publisher = threading.Thread(target=run, args=(settle_inputs, published))
            publisher.start()
            # Until the publish waits on a lock the scan holds, or finishes.
            deadline = time.monotonic() + 10
            while publisher.is_alive() and time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                    )
                    if cursor.fetchone()[0]:
                        break
                time.sleep(0.01)
            go.set()
            scan.join(10)
            publisher.join(20)
        self.assertFalse([r for r in results + published if isinstance(r, Exception)])
        return results[0]

    def start_late_feature(self, name):
        """A feature allocated in a new collection and held uncommitted."""
        allocated, release, done = [], threading.Event(), threading.Event()
        holder = threading.Thread(
            target=self.hold_insert, args=(None, allocated, release, done),
            kwargs={"new_collection": name},
        )
        holder.start()
        self.assertTrue(done.wait(5))

        def commit():
            release.set()
            holder.join(10)

        return allocated[0], commit

    def test_a_claim_in_flight_is_rewound_by_the_publish(self):
        dataset, _, _ = make_dataset("race-lease")
        fc, _ = make_collection("race-lease-fc", 1)
        settle_inputs()
        self.drain_leases()
        late, commit = self.start_late_feature("race-lease-late")
        FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(1.5, 1.5)))
        settle_inputs()

        lease = self.publish_while_paused(leases, claim_lease, commit)
        self.assertEqual(run_lease(lease), "completed")
        settle_inputs()
        self.drain_leases()
        self.assertTrue(ExtractTask.objects.filter(dataset_id=dataset.id, fm_id=late, status=1).exists())

    def test_a_coverage_chunk_in_flight_is_rewound_by_the_publish(self):
        dataset, _, _ = make_dataset("race-cov", is_global=False, extent=EXTENT)
        fc, _ = make_collection("race-cov-fc", 1)
        settle_inputs()
        self.drain_coverage()
        late, commit = self.start_late_feature("race-cov-late")
        FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(1.5, 1.5)))
        settle_inputs()

        self.assertIsNotNone(self.publish_while_paused(coverage, run_coverage_chunk, commit))
        settle_inputs()
        self.drain_coverage()
        late_geom = FeatMap.objects.get(id=late).geom_id
        self.assertEqual(Coverage.objects.get(dataset=dataset, geom_id=late_geom).status, 1)
