from unittest import mock

from django.test import TestCase

from analytics.models import ExtractTask, Request, RequestMap
from analytics.services import create_request
from analytics.tasks.requests import materialize_request_tasks
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ProcessingOption


class MaterializeRequestTasksTest(TestCase):
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

    def submit(self):
        return create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )

    def test_missing_request_logs_and_returns(self):
        # Must not raise for a request_id that doesn't exist (e.g. a retried
        # task after the request was somehow deleted).
        materialize_request_tasks("00000000-0000-0000-0000-000000000000")

    def test_success_creates_tasks_and_queues_the_request(self):
        created = self.submit()

        materialize_request_tasks(str(created.request.id))

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, -1)
        self.assertEqual(ExtractTask.objects.count(), 1)
        self.assertEqual(RequestMap.objects.count(), 1)

    def test_success_fires_the_dispatch_chain(self):
        created = self.submit()

        with (
            mock.patch("analytics.signals.chain") as mock_chain,
            self.captureOnCommitCallbacks(execute=True),
        ):
            materialize_request_tasks(str(created.request.id))

        mock_chain.assert_called_once()
        mock_chain.return_value.delay.assert_called_once()

    def test_no_extract_tasks_sets_error_status(self):
        created = self.submit()
        Dataset.objects.filter(pk=self.dataset.pk).update(public=False)

        materialize_request_tasks(str(created.request.id))

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, -2)
        self.assertIn("error", created.request.data)
        self.assertIn("error_detail", created.request.data)

    def test_unexpected_exception_sets_error_status_and_reraises(self):
        created = self.submit()

        with mock.patch(
            "analytics.tasks.requests.materialize_request",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                materialize_request_tasks(str(created.request.id))

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, -2)
        self.assertEqual(created.request.data["error"], "boom")
