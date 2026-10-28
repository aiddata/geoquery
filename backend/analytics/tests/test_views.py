from unittest import mock

from django.db import IntegrityError
from django.db.models.expressions import RawSQL
from django.test import TestCase
from django.urls import reverse

from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from analytics.services import materialize_request
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection


class RequestViewStandardSubmissionTest(TestCase):
    """RequestView.post's standard (non-custom-boundary) submission path.

    Covers on-demand ExtractTask materialization against the migration 0022
    unique indexes (rebuilt by migration 0024 to key on resource_ids_hash
    instead of raw resource_ids) on (dataset_id, fm_id, po_id,
    resource_ids_hash[, kwargs hash]), and RequestMap rows carrying the
    matching dataset_id.
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

    def test_concurrent_insert_is_adopted_and_bumped(self):
        # Simulates the race migration 0022's index exists for: two
        # concurrent materializations both miss _build_tasks' prefetch, and
        # the other one inserts the row first. This one's bulk insert must
        # skip it (ON CONFLICT DO NOTHING), and the re-read must adopt the
        # winner's row rather than crash or create a second one.
        #
        # The winner's row is inserted just before this one's bulk insert,
        # after the prefetch has already missed. Unlike a unique violation,
        # a skipped conflict doesn't abort the TestCase's enclosing
        # transaction, so Postgres resolves the collision for real.
        from analytics import services
        from analytics.models import Request

        payload = {
            "email": "a@example.com",
            "featureIds": [self.feature.id],
            "datasets": [{"datasetName": self.dataset.name}],
        }
        resp = self.client.post(
            self.url, data=payload, content_type="application/json"
        )
        req = Request.objects.get(id=resp.json()["id"])

        real_bulk_create = ExtractTask.objects.bulk_create
        winner = {}

        def insert_winner_first(objs, **kwargs):
            # The other writer creates its task at the default priority.
            winner["task"] = ExtractTask.objects.create(
                dataset_id=self.dataset.id,
                resource_ids=[self.resource.id],
                fm=self.fm,
                po=self.po,
            )
            return real_bulk_create(objs, **kwargs)

        with (
            mock.patch.object(
                ExtractTask.objects, "bulk_create", side_effect=insert_winner_first
            ) as mock_bulk_create,
            mock.patch.object(
                services, "_get_or_create_task", wraps=services._get_or_create_task
            ) as mock_get_or_create,
        ):
            materialize_request(req)

        mock_bulk_create.assert_called_once()
        self.assertTrue(mock_bulk_create.call_args.kwargs["ignore_conflicts"])
        # The re-read resolved it; the collision fallback never ran.
        mock_get_or_create.assert_not_called()

        task = ExtractTask.objects.get()
        self.assertEqual(task.id, winner["task"].id)
        # A request is waiting on it, so the winner's default priority is
        # raised as if this submission had created it.
        self.assertEqual(task.priority, 1)

        rm = RequestMap.objects.get(request_id=req.id)
        self.assertEqual(rm.task_id, task.id)
        self.assertEqual(rm.dataset_id, self.dataset.id)

    def test_get_or_create_task_falls_back_to_get_on_integrity_error(self):
        # _build_tasks reaches _get_or_create_task only on a resource_ids_hash
        # collision, which can't be staged here, so call it directly: the
        # initial .get() misses, another writer wins .create(), and the
        # IntegrityError must be recovered by re-fetching the winner's row.
        #
        # .create() stands in for the collision: it inserts the winner's
        # row, then raises as the unique index would. The IntegrityError is
        # raised in Python rather than by Postgres because a real one would
        # abort the TestCase's enclosing transaction; in production
        # _build_tasks runs in autocommit.
        from types import SimpleNamespace

        from analytics.services import _get_or_create_task

        resolved = SimpleNamespace(dataset=self.dataset, task_kwargs=None)
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
            task = _get_or_create_task(resolved, self.fm, self.resource, self.po)

        self.assertEqual(task, winner["task"])
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


class RequestViewCustomBoundaryPermissionTest(TestCase):
    """Custom boundary submissions are limited to beta testers while in beta."""

    def setUp(self):
        self.url = reverse("request-list-create")
        self.payload = {
            "email": "a@example.com",
            "datasets": [{"datasetName": "ds"}],
            "customBoundary": {
                "fileName": "upload.geojson",
                "featureCount": 1,
                "features": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {"type": "Point", "coordinates": [0, 0]},
                        }
                    ],
                },
            },
        }

    def submit(self):
        return self.client.post(
            self.url, data=self.payload, content_type="application/json"
        )

    def make_user(self, username):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(
            username=username, email=f"{username}@example.com"
        )

    def test_anonymous_is_rejected(self):
        resp = self.submit()

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Request.objects.exists())

    def test_user_without_permission_is_rejected(self):
        self.client.force_login(self.make_user("plain"))

        resp = self.submit()

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Request.objects.exists())

    @mock.patch("analytics.views.ingest_custom_boundary_task.delay")
    def test_beta_tester_is_accepted(self, delay):
        from django.contrib.auth.models import Permission

        user = self.make_user("tester")
        user.user_permissions.add(Permission.objects.get(codename="beta_tester"))
        self.client.force_login(user)

        resp = self.submit()

        self.assertEqual(resp.status_code, 201)
        delay.assert_called_once()

    @mock.patch("accounts.features.BETA_FEATURES", frozenset())
    @mock.patch("analytics.views.ingest_custom_boundary_task.delay")
    def test_anonymous_is_accepted_once_released(self, delay):
        resp = self.submit()

        self.assertEqual(resp.status_code, 201)
        delay.assert_called_once()


class RequestDetailVisualizationLinkTest(TestCase):
    """The detail view resolves the session so the viz link follows the viewer."""

    def setUp(self):
        self.req = Request.objects.create(contact="a@example.com", status=1, data={})
        self.url = reverse("request-detail", args=[self.req.id])

    def test_link_hidden_from_anonymous_viewers(self):
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("visualization_url", resp.json())

    def test_link_shown_to_beta_testers(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        user = get_user_model().objects.create_user(
            username="tester", email="tester@example.com"
        )
        user.user_permissions.add(Permission.objects.get(codename="beta_tester"))
        self.client.force_login(user)

        resp = self.client.get(self.url)

        self.assertIn(f"/viz/{self.req.id}", resp.json()["visualization_url"])
