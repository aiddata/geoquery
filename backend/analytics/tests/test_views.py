from unittest import mock

from django.db import IntegrityError
from django.db.models.expressions import RawSQL
from django.test import TestCase
from django.urls import reverse

from analytics.models import ExtractTask, ProcessingOption, RequestMap
from analytics.services import materialize_request
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection


class RequestViewStandardSubmissionTest(TestCase):
    """RequestView.post's standard (non-custom-boundary) submission path.

    Covers the on-demand ExtractTask get-or-create against the migration
    0022 unique indexes (rebuilt by migration 0024 to key on
    resource_ids_hash instead of raw resource_ids) on (dataset_id, fm_id,
    po_id, resource_ids_hash[, kwargs hash]), and RequestMap rows carrying
    the matching dataset_id.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="ds", path="/data/ds", active=True, public=True
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
            public=True,
        )
        self.fc = FeatureCollection.objects.create(
            name="fc", path="/data/fc", active=True, public=True
        )
        self.feature = Feature.objects.create(shape="POINT(0 0)")
        self.fm = FeatMap.objects.create(fc=self.fc, geom=self.feature)
        self.url = reverse("request-list-create")

    def submit(self, **overrides):
        payload = {
            "email": "a@example.com",
            "featureIds": [self.feature.id],
            "datasets": [{"datasetName": self.dataset.name}],
        }
        payload.update(overrides)
        resp = self.client.post(
            self.url, data=payload, content_type="application/json"
        )
        if resp.status_code == 201:
            from analytics.models import Request

            req = Request.objects.get(id=resp.json()["id"])
            materialize_request(req)
        return resp

    def test_creates_task_with_dataset_id_and_resource_ids(self):
        resp = self.submit()

        self.assertEqual(resp.status_code, 201)
        tasks = list(ExtractTask.objects.all())
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task.dataset_id, self.dataset.id)
        self.assertEqual(task.resource_ids, [self.resource.id])
        self.assertEqual(task.priority, 1)

    def test_request_map_carries_dataset_id(self):
        resp = self.submit()

        req_id = resp.json()["id"]
        maps = list(RequestMap.objects.filter(request_id=req_id))
        self.assertEqual(len(maps), 1)
        self.assertEqual(maps[0].dataset_id, self.dataset.id)
        self.assertEqual(maps[0].task.dataset_id, self.dataset.id)

    def test_resubmission_with_no_kwargs_reuses_existing_task(self):
        self.submit()
        first_id = ExtractTask.objects.get().id

        resp = self.submit()

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(ExtractTask.objects.count(), 1)
        self.assertEqual(ExtractTask.objects.get().id, first_id)

    def test_kwargs_variants_create_distinct_tasks(self):
        self.submit()
        self.submit(
            datasets=[
                {"datasetName": self.dataset.name, "kwargs": {"buffer": 10}}
            ]
        )

        self.assertEqual(ExtractTask.objects.count(), 2)
        self.assertCountEqual(
            [t.kwargs for t in ExtractTask.objects.all()], [None, {"buffer": 10}]
        )

    def test_resubmission_with_same_kwargs_reuses_task(self):
        ds_with_kwargs = [
            {"datasetName": self.dataset.name, "kwargs": {"buffer": 10}}
        ]
        self.submit(datasets=ds_with_kwargs)
        first_id = ExtractTask.objects.get().id

        self.submit(datasets=ds_with_kwargs)

        self.assertEqual(ExtractTask.objects.count(), 1)
        self.assertEqual(ExtractTask.objects.get().id, first_id)

    def test_priority_bumped_on_resubmission_of_deprioritized_task(self):
        self.submit()
        task = ExtractTask.objects.get()
        task.priority = 0
        task.save(update_fields=["priority"])

        self.submit()

        task.refresh_from_db()
        self.assertEqual(task.priority, 1)

    def test_integrity_error_on_create_falls_back_to_get(self):
        # Simulates the race migration 0022's index exists for: two
        # concurrent materializations both miss the initial .get()
        # (DoesNotExist), one wins .create(), the other must hit
        # IntegrityError and recover by re-fetching the winner's row rather
        # than crashing.
        #
        # The winner's row has to appear *after* _build_tasks' bulk prefetch,
        # or the prefetch finds it and the get-or-create fallback never runs.
        # So .create() stands in for the collision: it inserts the "other
        # request's" winning row, then raises as the unique index would. The
        # IntegrityError is raised in Python rather than by Postgres because a
        # real one would abort the TestCase's enclosing transaction; in
        # production _build_tasks runs in autocommit, outside
        # materialize_request's atomic block.
        from analytics.models import Request
        from analytics.services import materialize_request

        payload = {
            "email": "a@example.com",
            "featureIds": [self.feature.id],
            "datasets": [{"datasetName": self.dataset.name}],
        }
        resp = self.client.post(
            self.url, data=payload, content_type="application/json"
        )
        req = Request.objects.get(id=resp.json()["id"])

        winner = {}

        def insert_winner_then_collide(**fields):
            winner["task"] = ExtractTask.objects.bulk_create(
                [ExtractTask(**fields)]
            )[0]
            raise IntegrityError

        def get_winner(**lookup):
            if "task" not in winner:
                raise ExtractTask.DoesNotExist
            return winner["task"]

        with (
            mock.patch.object(
                ExtractTask.objects, "get", side_effect=get_winner
            ) as mock_get,
            mock.patch.object(
                ExtractTask.objects,
                "create",
                side_effect=insert_winner_then_collide,
            ) as mock_create,
        ):
            materialize_request(req)

        mock_create.assert_called_once_with(
            dataset_id=self.dataset.id,
            resource_ids=[self.resource.id],
            fm=self.fm,
            po=self.po,
            kwargs=None,
        )
        expected_hash = RawSQL(
            "extract_tasks_resource_ids_hash(%s)", [[self.resource.id]]
        )
        expected_get_kwargs = {
            "dataset_id": self.dataset.id,
            "resource_ids": [self.resource.id],
            "resource_ids_hash": expected_hash,
            "fm": self.fm,
            "po": self.po,
            "kwargs__isnull": True,
        }
        self.assertEqual(mock_get.call_count, 2)
        for call in mock_get.call_args_list:
            self.assertEqual(call.kwargs, expected_get_kwargs)

        rm = RequestMap.objects.get(request_id=req.id)
        self.assertEqual(rm.task_id, winner["task"].id)
        self.assertEqual(rm.dataset_id, self.dataset.id)
