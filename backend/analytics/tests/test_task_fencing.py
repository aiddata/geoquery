"""The task-row path against changing inputs: claim, load and flush."""

from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase

from analytics.changes import InputStateMissing, lock_states
from analytics.models import ExtractData, ExtractInputState, ExtractTask, ExtractTaskBuildProgress, Request, RequestMap
from analytics.tasks import processing
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from datasets.models import DatasetResource
from features.models import FeatMap, Feature


class TaskFencingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset, cls.po, (cls.resource,) = make_dataset("fence")
        cls.fc, cls.fms = make_collection("fence-fc", 2)
        settle_inputs()

    def task(self, fm=None, **fields):
        return ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=fm or self.fms[0],
            po=self.po, **fields)

    def test_tasks_with_a_reset_pending_are_not_claimed(self):
        task = self.task()
        req = Request.objects.create(contact="a@b.c", status=-1, data={})
        RequestMap.objects.create(request=req, task=task, dataset_id=self.dataset.id)
        Feature.objects.filter(id=self.fms[0].geom_id).update(shape=Point(9, 9))
        self.assertEqual(processing.claim_pending_tasks(5), [])
        settle_inputs()
        self.assertEqual(processing.claim_pending_tasks(5), [(task.id, self.dataset.id)])

    def test_an_addition_does_not_hold_a_task_back(self):
        task = self.task()
        FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(9, 9)))
        self.assertEqual(processing.claim_pending_tasks(5), [(task.id, self.dataset.id)])

    def test_an_uploads_request_tasks_run_without_waiting_for_sync(self):
        _, (up_fm,) = make_collection("fence-up", 1, upload=True)
        task = self.task(fm=up_fm)
        self.assertEqual(processing.claim_pending_tasks(5), [(task.id, self.dataset.id)])

    def test_an_input_change_between_load_and_flush_releases_the_task(self):
        task = self.task()
        [(task_id, dataset_id)] = processing.claim_pending_tasks(1)
        outcomes = []
        with mock.patch.object(processing, "get_func", return_value=lambda g, p, **kw: [("mean", 3.0)]):
            processing._run_extract_task(task_id, dataset_id, outcomes=outcomes)
        # The raster is replaced while the result waits in the buffer.
        DatasetResource.objects.filter(id=self.resource.id).update(path="v2.tif")
        processing._flush_outcomes(outcomes)
        task.refresh_from_db()
        self.assertEqual(task.status, 0)
        self.assertFalse(ExtractData.objects.filter(dataset_id=self.dataset.id, extract_task_id=task.id).exists())

    def test_a_task_whose_inputs_went_dirty_after_its_claim_is_deferred_not_failed(self):
        task = self.task()
        [(task_id, dataset_id)] = processing.claim_pending_tasks(1)
        Feature.objects.filter(id=self.fms[0].geom_id).update(shape=Point(8, 8))
        outcomes = []
        processing._run_extract_task(task_id, dataset_id, outcomes=outcomes)
        self.assertEqual(outcomes, [])
        task.refresh_from_db()
        self.assertEqual((task.status, task.attempts), (0, 0))

    def test_retired_background_tasks_wait_until_a_request_needs_them(self):
        retired = ExtractTaskBuildProgress.objects.create(
            resource_ids=[self.resource.id, 10**6], po=self.po, dataset_id=self.dataset.id, current=False)
        task = self.task(pair_id=retired.id)
        self.assertEqual(processing.claim_pending_tasks(5), [])
        req = Request.objects.create(contact="a@b.c", status=-1, data={})
        RequestMap.objects.create(request=req, task=task, dataset_id=self.dataset.id)
        self.assertEqual(processing.claim_pending_tasks(5), [(task.id, self.dataset.id)])

    def test_a_scope_without_state_is_never_clean(self):
        task = self.task()
        ExtractInputState.objects.filter(kind="collection", object_id=self.fc.id).delete()
        self.assertEqual(processing.claim_pending_tasks(5), [])
        from django.db import transaction

        with transaction.atomic(), self.assertRaises(InputStateMissing):
            lock_states([self.dataset.id], [self.fc.id])
        self.assertEqual(ExtractTask.objects.get(id=task.id).status, 0)
