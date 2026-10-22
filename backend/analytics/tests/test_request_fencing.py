"""Requests against changing inputs: materialization, readiness and output."""

import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase

from analytics.management.commands.manage_user_requests import (
    _check_request_tasks, _manage_user_requests,
)
from analytics.models import ExtractTask, Request, RequestMap
from analytics.services import MaterializationDeferred, create_request, materialize_request
from analytics.tasks.requests import materialize_request_tasks
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature

SWEEP = "analytics.management.commands.manage_user_requests"


class RequestFencingTests(TestCase):
    def setUp(self):
        self.dataset, self.po, (self.resource,) = make_dataset("req")
        Dataset.objects.filter(id=self.dataset.id).update(public=True)
        self.po.public = True
        self.po.save()
        self.fc, self.fms = make_collection("req-fc", 2)
        self.fc.public = True
        self.fc.save()
        settle_inputs()

    def submit(self):
        return create_request(
            user=None, contact="a@example.com", name=None,
            feature_ids=[fm.geom_id for fm in self.fms],
            datasets=[{"datasetName": self.dataset.name}],
        ).request

    def test_materialization_waits_while_an_input_is_being_reset(self):
        req = self.submit()
        DatasetResource.objects.filter(id=self.resource.id).update(path="v2.tif")
        with self.assertRaises(MaterializationDeferred):
            materialize_request(req)
        req.refresh_from_db()
        self.assertEqual(req.status, 4)
        self.assertFalse(RequestMap.objects.filter(request=req).exists())

        with mock.patch.object(materialize_request_tasks, "apply_async") as retry:
            materialize_request_tasks(str(req.id))
        retry.assert_called_once()
        req.refresh_from_db()
        self.assertEqual(req.status, 4)  # not the user's error

        settle_inputs()
        materialize_request(req)
        req.refresh_from_db()
        self.assertEqual(req.status, -1)
        self.assertEqual(req.data["task_count"], 2)

    def test_a_pure_addition_does_not_hold_materialization_back(self):
        req = self.submit()
        FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(9, 9)))
        materialize_request(req)
        req.refresh_from_db()
        self.assertEqual(req.status, -1)

    def test_tasks_deleted_with_their_boundary_fail_the_request_visibly(self):
        req = self.submit()
        materialize_request(req)
        ExtractTask.objects.update(status=1)
        self.fms[1].geom.delete()  # cascades feat_map, task and request_map rows
        settle_inputs()
        with mock.patch(f"{SWEEP}._notify_user"), mock.patch(f"{SWEEP}._build_output") as build:
            _manage_user_requests()
        build.assert_not_called()
        req.refresh_from_db()
        self.assertEqual(req.status, -2)

    def test_output_built_from_inputs_that_changed_mid_build_is_discarded(self):
        req = self.submit()
        materialize_request(req)
        ExtractTask.objects.update(status=1)
        with tempfile.TemporaryDirectory() as requests_dir:
            staged = Path(requests_dir) / f".{req.id}.building.test"

            def build(request, task_map, download, rdir, adir, stage_only=False):
                staged.mkdir()
                (staged / "out.csv").write_text("stale")
                # A boundary is reshaped while the output is being written.
                Feature.objects.filter(id=self.fms[0].geom_id).update(shape=Point(5, 5))
                return staged

            with mock.patch(f"{SWEEP}._notify_user"), mock.patch(f"{SWEEP}._build_output", side_effect=build):
                _manage_user_requests(requests_dir=requests_dir)
            req.refresh_from_db()
            self.assertEqual(req.status, 0)  # requeued, not failed
            self.assertFalse(staged.exists())
            self.assertFalse((Path(requests_dir) / str(req.id)).exists())

    def test_output_is_published_only_by_the_fenced_completion(self):
        req = self.submit()
        materialize_request(req)
        ExtractTask.objects.update(status=1)
        with tempfile.TemporaryDirectory() as requests_dir:
            staged = Path(requests_dir) / f".{req.id}.building.test"

            def build(request, task_map, download, rdir, adir, stage_only=False):
                self.assertTrue(stage_only)
                staged.mkdir()
                (staged / "out.csv").write_text("fresh")
                self.assertFalse((Path(requests_dir) / str(req.id)).exists())
                return staged

            with mock.patch(f"{SWEEP}._notify_user"), mock.patch(f"{SWEEP}._build_output", side_effect=build):
                _manage_user_requests(requests_dir=requests_dir)
            req.refresh_from_db()
            self.assertEqual(req.status, 1)
            self.assertEqual((Path(requests_dir) / str(req.id) / "out.csv").read_text(), "fresh")

    def test_a_reset_published_after_the_readiness_check_is_not_merged(self):
        req = self.submit()
        materialize_request(req)
        ExtractTask.objects.update(status=1)

        def check_then_reset(request, dry_run=False):
            result = _check_request_tasks(request, dry_run=dry_run)
            # A boundary is reshaped, and its reset published, before the
            # sweep captures the input generations.
            Feature.objects.filter(id=self.fms[0].geom_id).update(shape=Point(5, 5))
            settle_inputs()
            return result

        with (
            mock.patch(f"{SWEEP}._notify_user"),
            mock.patch(f"{SWEEP}._check_request_tasks", side_effect=check_then_reset),
            mock.patch(f"{SWEEP}._build_output") as build,
        ):
            _manage_user_requests()
        build.assert_not_called()
        req.refresh_from_db()
        self.assertEqual(req.status, 0)

    def test_requests_wait_while_their_inputs_are_mid_change(self):
        req = self.submit()
        materialize_request(req)
        ExtractTask.objects.update(status=1)
        Feature.objects.filter(id=self.fms[0].geom_id).update(shape=Point(8, 8))
        with mock.patch(f"{SWEEP}._notify_user"), mock.patch(f"{SWEEP}._build_output") as build:
            _manage_user_requests()
        build.assert_not_called()
        req.refresh_from_db()
        self.assertEqual(req.status, 0)

    def test_an_addition_does_not_hold_a_finished_request_back(self):
        req = self.submit()
        materialize_request(req)
        ExtractTask.objects.update(status=1)
        FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(8, 8)))
        with mock.patch(f"{SWEEP}._notify_user"), \
                mock.patch(f"{SWEEP}._build_output", return_value=None) as build:
            _manage_user_requests()
        build.assert_called_once()
        req.refresh_from_db()
        self.assertEqual(req.status, 1)

    def test_completed_downloads_are_historical_snapshots(self):
        req = self.submit()
        materialize_request(req)
        Request.objects.filter(id=req.id).update(status=1)
        DatasetResource.objects.filter(id=self.resource.id).update(path="v3.tif")
        settle_inputs()
        req.refresh_from_db()
        self.assertEqual(req.status, 1)
