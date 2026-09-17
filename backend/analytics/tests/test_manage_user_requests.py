import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from analytics.management.commands.manage_user_requests import _manage_user_requests
from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from analytics.services import create_request, materialize_request
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection


class SweepIgnoresMaterializingRequestsTest(TestCase):
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

    def test_sweep_does_not_touch_a_materializing_request(self):
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )
        self.assertEqual(created.request.status, 4)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ) as mock_build_output, mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ) as mock_send_email:
            _manage_user_requests()

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, 4)
        self.assertEqual(ExtractTask.objects.count(), 0)
        self.assertEqual(RequestMap.objects.count(), 0)
        mock_build_output.assert_not_called()
        mock_send_email.assert_not_called()


class FullSubmissionToCompletionFlowTest(TestCase):
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

    def test_submit_materialize_sweep_reaches_completed(self):
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )

        materialize_request(created.request)
        created.request.refresh_from_db()
        self.assertEqual(created.request.status, -1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        created.request.refresh_from_db()
        # Not done yet -- the one ExtractTask hasn't run.
        self.assertEqual(created.request.status, 0)

        ExtractTask.objects.update(status=1)

        with tempfile.TemporaryDirectory() as tmp_requests_dir:
            # Let _build_output run for real this time (only _notify_user is
            # mocked) so completion actually proves a downloadable artifact
            # was produced, not just that status flipped to 1.
            with mock.patch(
                "analytics.management.commands.manage_user_requests._notify_user"
            ):
                _manage_user_requests(requests_dir=tmp_requests_dir)

            created.request.refresh_from_db()
            self.assertEqual(created.request.status, 1)

            # _build_output zips request_dir's contents and then moves that
            # zip to replace request_dir itself, so the final artifact is a
            # request_id-named zip file sitting at request_dir/request_id.zip
            # (manage_user_requests.py:394-396) -- the same path
            # _notify_user's completion email and DocBuilder's download link
            # point at.
            request_id = str(created.request.id)
            output_zip = Path(tmp_requests_dir) / request_id / f"{request_id}.zip"
            self.assertTrue(output_zip.is_file())
