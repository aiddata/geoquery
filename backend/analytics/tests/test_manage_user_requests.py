import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from analytics.management.commands.manage_user_requests import (
    _claim_request,
    _manage_user_requests,
)
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


class SweepClaimTests(TestCase):
    """status=2 as a real, committed claim (see the design doc's
    'The claim marker that cannot claim')."""

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
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )
        materialize_request(created.request)
        created.request.refresh_from_db()
        return created.request

    def test_claimed_request_is_not_picked_up_again(self):
        # A request already claimed by another sweep (status=2) must be
        # invisible to this one -- no status change, no output built.
        req = self.submit()
        Request.objects.filter(id=req.id).update(status=2)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ) as mock_build, mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        mock_build.assert_not_called()

    def test_claim_is_written_before_build_runs(self):
        # Ordering only: status=2 must be written before _build_output starts.
        # This deliberately does NOT prove the claim is *committed* by then --
        # TestCase runs the whole test in one transaction on one connection,
        # so a read here sees uncommitted writes identically to committed
        # ones. Cross-connection commit visibility is covered separately by
        # ClaimContentionTest (TransactionTestCase).
        req = self.submit()
        ExtractTask.objects.update(status=1)
        observed = {}

        def capture(*args, **kwargs):
            # Re-query rather than reuse the ORM cache, so this reflects the
            # row as the database has it at this point in the sweep.
            observed["status"] = Request.objects.get(id=req.id).status

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output",
            side_effect=capture,
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        self.assertEqual(observed.get("status"), 2)
        req.refresh_from_db()
        self.assertEqual(req.status, 1)

    def test_claim_is_not_reclaimable_once_taken(self):
        # _claim_request's status__in=(-1, 0) filter is what makes the claim
        # exclusive: once it has moved the row to 2, a second sweep arriving
        # with the same request_id gets (False, None) rather than a second
        # claim on work already in flight.
        req = self.submit()

        claimed, original_status = _claim_request(str(req.id))
        self.assertTrue(claimed)
        self.assertEqual(original_status, -1)

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        self.assertIsNotNone(req.prepare_time)
        self.assertIsNotNone(req.process_time)

        self.assertEqual(_claim_request(str(req.id)), (False, None))

    def test_dry_run_writes_no_status(self):
        req = self.submit()
        self.assertEqual(req.status, -1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests(dry_run=True)

        req.refresh_from_db()
        self.assertEqual(req.status, -1)
