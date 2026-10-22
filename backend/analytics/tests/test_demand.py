"""extract_work_demand(), the autoscaler's estimate of outstanding work."""

import uuid
from datetime import timedelta

from django.contrib.gis.geos import Polygon
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from analytics.models import (
    CoverageProgress, ExtractTask, ExtractTaskBuildProgress, ExtractTaskLease, Request, RequestMap,
)
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from datasets.models import Dataset, DatasetResource


def demand():
    with connection.cursor() as cursor:
        cursor.execute("SELECT extract_work_demand()")
        return cursor.fetchone()[0]


class DemandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset, cls.po, (cls.resource,) = make_dataset("demand")
        cls.fc, cls.fms = make_collection("demand-fc", 4)
        settle_inputs()
        cls.pair = ExtractTaskBuildProgress.objects.get(dataset_id=cls.dataset.id)
        cls.max_fm = cls.fms[-1].id

    def test_unscanned_pair_ranges_count(self):
        self.assertEqual(demand(), self.max_fm)
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=self.max_fm)
        self.assertEqual(demand(), 0)

    def test_outstanding_leases_count_by_their_features(self):
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=self.max_fm)
        ExtractTaskLease.objects.create(
            progress=self.pair, dataset_id=self.dataset.id, resource_ids=[self.resource.id],
            po_id=self.po.id, fm_ids=[fm.id for fm in self.fms[:3]], token=uuid.uuid4(),
            leased_until=timezone.now() + timedelta(minutes=5),
        )
        self.assertEqual(demand(), 3)

    def test_pending_tasks_count_unless_parked_or_retired(self):
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=self.max_fm)
        ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=self.fms[0], po=self.po)
        retired = ExtractTaskBuildProgress.objects.create(
            resource_ids=[999], po=self.po, dataset_id=self.dataset.id, current=False)
        orphan = ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[999], fm=self.fms[1], po=self.po, pair_id=retired.id)
        self.assertEqual(demand(), 1)
        # A request still needing a retired pair's task makes it runnable again.
        req = Request.objects.create(contact="a@b.c", status=-1, data={})
        RequestMap.objects.create(request=req, task=orphan, dataset_id=self.dataset.id)
        self.assertEqual(demand(), 2)

    def test_inactive_and_resetting_datasets_contribute_nothing(self):
        Dataset.objects.filter(id=self.dataset.id).update(active=False)
        self.assertEqual(demand(), 0)
        settle_inputs()
        self.assertEqual(demand(), 0)
        Dataset.objects.filter(id=self.dataset.id).update(active=True)
        settle_inputs()
        # An addition leaves existing work runnable while sync catches up.
        DatasetResource.objects.create(dataset=self.dataset, name="demand-r2", path="r2.tif")
        self.assertEqual(demand(), self.max_fm)
        # A reset of the whole dataset parks it until sync publishes.
        Dataset.objects.filter(id=self.dataset.id).update(path="/data/demand-v2")
        self.assertEqual(demand(), 0)

    def test_uploads_raise_no_demand(self):
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=self.max_fm)
        make_collection("demand-upload", 3, upload=True)
        self.assertEqual(demand(), 0)
        settle_inputs()
        self.pair.refresh_from_db()
        self.assertEqual(self.pair.cursor_fm_id, self.max_fm)

    def test_demand_counts_exactly_the_tasks_a_claim_would_take(self):
        from analytics.tasks import processing

        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=self.max_fm)
        req = Request.objects.create(contact="a@b.c", status=-1, data={})

        def pending(fm, po=None):
            task = ExtractTask.objects.create(
                dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=fm, po=po or self.po)
            RequestMap.objects.create(request=req, task=task, dataset_id=self.dataset.id)
            return task

        runnable = pending(self.fms[0])
        # Parked: an inactive option, an inactive collection, a reset pending.
        other_po = type(self.po).objects.create(
            dataset=self.dataset, short_name="off", function="rasterstats_default_mean", active=False)
        pending(self.fms[1], po=other_po)
        off_fc, (off_fm,) = make_collection("demand-off", 1, active=False)
        pending(off_fm)
        pending(self.fms[2])
        settle_inputs()
        ExtractTaskBuildProgress.objects.filter(dataset_id=self.dataset.id).update(cursor_fm_id=10**6)
        from features.models import Feature
        Feature.objects.filter(id=self.fms[2].geom_id).update(shape=Polygon(((5, 5), (6, 5), (6, 6), (5, 5))))

        self.assertEqual(demand(), 1)
        self.assertEqual(processing.claim_pending_tasks(10), [(runnable.id, self.dataset.id)])

    def test_non_global_work_is_capped_by_coverage_and_uncovered_ranges_count(self):
        ExtractTaskBuildProgress.objects.filter(id=self.pair.id).update(cursor_fm_id=self.max_fm)
        local, _, _ = make_dataset("demand-local", is_global=False,
                                   extent=Polygon(((0, 0), (9, 0), (9, 9), (0, 9), (0, 0))))
        settle_inputs()
        # Uncovered range only: the pair's cap is the watermark, 0.
        self.assertEqual(demand(), self.max_fm)
        CoverageProgress.objects.filter(dataset=local).update(covered_up_to_fm_id=self.max_fm)
        self.assertEqual(demand(), self.max_fm)  # now the pair's range instead
