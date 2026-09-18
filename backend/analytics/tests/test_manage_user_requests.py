import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from analytics.management.commands import manage_user_requests as mur
from analytics.management.commands.manage_user_requests import (
    RequestClaim,
    _build_output,
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


class BuildOutputAtomicityTests(TestCase):
    """_build_output must not let two concurrent builds corrupt each other.

    Task 1's claim fence prevents a stale sweep from *finalizing* a request,
    but not from running _build_output concurrently with its replacement once
    the reaper can reset a still-running build. rmtree-in-place made that
    data-destructive.
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

    def build(self, requests_dir):
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )
        materialize_request(created.request)
        created.request.refresh_from_db()
        ExtractTask.objects.update(status=1)
        task_map = {
            t.id: t.dataset_id for t in ExtractTask.objects.all()
        }
        _build_output(created.request, task_map, "", requests_dir, "../assets")
        return str(created.request.id)

    def test_output_lands_at_the_expected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_id = self.build(tmp)
            self.assertTrue(
                (Path(tmp) / request_id / f"{request_id}.zip").is_file()
            )

    def test_no_temp_directory_is_left_behind_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_id = self.build(tmp)
            leftovers = [
                p.name for p in Path(tmp).iterdir() if p.name != request_id
            ]
            self.assertEqual(leftovers, [])

    def test_failed_build_leaves_no_partial_request_dir(self):
        # A build that dies partway must not leave a half-written
        # request_dir that a later reader would mistake for real output.
        with tempfile.TemporaryDirectory() as tmp:
            created = create_request(
                user=None,
                contact="a@example.com",
                name=None,
                feature_ids=[self.feature.id],
                datasets=[{"datasetName": self.dataset.name}],
            )
            materialize_request(created.request)
            created.request.refresh_from_db()
            ExtractTask.objects.update(status=1)
            task_map = {t.id: t.dataset_id for t in ExtractTask.objects.all()}

            with mock.patch(
                "analytics.management.commands.manage_user_requests.DocBuilder",
                side_effect=RuntimeError("boom"),
            ):
                with self.assertRaises(RuntimeError):
                    _build_output(
                        created.request, task_map, "", tmp, "../assets"
                    )

            self.assertFalse((Path(tmp) / str(created.request.id)).exists())

    def test_interleaved_builds_do_not_corrupt_each_other(self):
        # Once a reaper can reset a claim out from under a running build, two
        # sweeps can be inside _build_output for the same request at the same
        # time. Rather than threads, run a second build to completion from
        # inside the first one's DocBuilder step -- the same interleaving,
        # deterministically. Both must finish, and the surviving directory
        # must be one build's output rather than a mix.
        with tempfile.TemporaryDirectory() as tmp:
            created = create_request(
                user=None,
                contact="a@example.com",
                name=None,
                feature_ids=[self.feature.id],
                datasets=[{"datasetName": self.dataset.name}],
            )
            materialize_request(created.request)
            created.request.refresh_from_db()
            ExtractTask.objects.update(status=1)
            task_map = {t.id: t.dataset_id for t in ExtractTask.objects.all()}
            request_id = str(created.request.id)

            real_doc_builder = mur.DocBuilder
            state = {"nested_done": False}

            def build_concurrently(*args, **kwargs):
                if not state["nested_done"]:
                    state["nested_done"] = True
                    _build_output(
                        created.request, task_map, "", tmp, "../assets"
                    )
                return real_doc_builder(*args, **kwargs)

            with mock.patch.object(
                mur, "DocBuilder", side_effect=build_concurrently
            ):
                _build_output(created.request, task_map, "", tmp, "../assets")

            self.assertTrue(state["nested_done"])

            request_dir = Path(tmp) / request_id
            output_zip = request_dir / f"{request_id}.zip"
            self.assertTrue(output_zip.is_file())
            self.assertEqual(
                [p.name for p in Path(tmp).iterdir() if p.name != request_id],
                [],
            )

            # Consistency: the zip is readable, holds exactly one build's
            # files (no zip nested inside it from the other build), and its
            # contents match what sits alongside it on disk.
            with zipfile.ZipFile(output_zip) as zf:
                self.assertIsNone(zf.testzip())
                zipped = set(zf.namelist())
            self.assertNotIn(f"{request_id}.zip", zipped)
            on_disk = {p.name for p in request_dir.iterdir()}
            self.assertEqual(
                zipped - {"GeoQuery_Goodman2019.pdf"},
                on_disk - {f"{request_id}.zip"},
            )


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
        # invisible to this one. Two requests, not one: with a single claimed
        # request the queue is empty, the sweep returns before the loop body,
        # and "no output built" would hold for the wrong reason. The second
        # request proves the sweep really ran and built only the unclaimed one.
        claimed_req = self.submit()
        other_req = self.submit()
        Request.objects.filter(id=claimed_req.id).update(status=2)
        ExtractTask.objects.update(status=1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ) as mock_build, mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        claimed_req.refresh_from_db()
        other_req.refresh_from_db()
        self.assertEqual(claimed_req.status, 2)
        self.assertEqual(other_req.status, 1)

        built_ids = [str(call.args[0].id) for call in mock_build.call_args_list]
        self.assertEqual(built_ids, [str(other_req.id)])

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
        # with the same request_id gets RequestClaim(False) rather than a
        # second claim on work already in flight.
        req = self.submit()

        claim = _claim_request(str(req.id))
        self.assertTrue(claim.claimed)
        self.assertEqual(claim.original_status, -1)
        self.assertTrue(claim.first_claim)

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        self.assertIsNotNone(req.prepare_time)
        self.assertEqual(req.process_time, claim.claim_time)

        self.assertEqual(_claim_request(str(req.id)), RequestClaim(False))

    def test_lost_claim_is_not_reverted_to_queued(self):
        # Sibling of test_lost_claim_is_not_finalized for the not-ready path.
        # Tasks are still pending, so the sweep takes the missing_items branch;
        # the claim is taken over while it checks them. The stale owner must
        # not write status=0 over the new owner's claim, which would make the
        # request claimable by a third sweep while the new owner still builds.
        req = self.submit()  # ExtractTasks left pending -> missing_items > 0

        def takeover(*args, **kwargs):
            Request.objects.filter(id=req.id).update(
                status=2, process_time=timezone.now()
            )
            return 1, {}  # pending count, merge map

        with mock.patch(
            "analytics.management.commands.manage_user_requests._check_request_tasks",
            side_effect=takeover,
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        req.refresh_from_db()
        self.assertEqual(req.status, 2)

    def test_received_email_is_not_resent_after_error_reset(self):
        # reset_errored_requests blanket-resets status -2 -> -1 in raw SQL and
        # never touches prepare_time. Gating the acknowledgement on status
        # would therefore re-send it once per error/reset cycle, unbounded;
        # gating on prepare_time (first_claim) sends it exactly once.
        req = self.submit()
        ExtractTask.objects.update(status=1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ) as first_notify:
            _manage_user_requests()

        received = [c for c in first_notify.call_args_list if c.args[2] == 0]
        self.assertEqual(len(received), 1)

        # The error-and-reset cycle: status goes back to -1, prepare_time stays.
        Request.objects.filter(id=req.id).update(status=-1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ) as second_notify:
            _manage_user_requests()

        resent = [c for c in second_notify.call_args_list if c.args[2] == 0]
        self.assertEqual(resent, [])

    def test_lost_claim_is_not_finalized(self):
        # The reaper (Task 2) resets a stale status=2 back to 0 after 30
        # minutes, so a slow build can have its request re-claimed by another
        # sweep while it is still running. The stale owner must not then mark
        # the request complete or email a download link, because the new owner
        # is mid-build on the same directory (_build_output opens with an
        # rmtree). The process_time fence is what detects the takeover.
        req = self.submit()
        ExtractTask.objects.update(status=1)

        def takeover(*args, **kwargs):
            # Another sweep re-claims mid-build: same row, new claim fence.
            Request.objects.filter(id=req.id).update(
                status=2, process_time=timezone.now()
            )

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output",
            side_effect=takeover,
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ) as mock_notify:
            _manage_user_requests()

        req.refresh_from_db()
        # Still the new owner's claim -- the stale owner did not finalize.
        self.assertEqual(req.status, 2)
        self.assertIsNone(req.complete_time)

        # The received email (status arg 0) is fine; a completion email
        # (status arg 1) would have pointed at a zip still being written.
        completion_calls = [
            call for call in mock_notify.call_args_list if call.args[2] == 1
        ]
        self.assertEqual(completion_calls, [])

    def test_received_email_is_sent_before_build(self):
        # Sent at claim time, not at the end of the iteration: a crash
        # mid-build otherwise loses it permanently, since the reaper resets
        # the request to 0 and the retry sees original_status == 0.
        req = self.submit()
        ExtractTask.objects.update(status=1)
        sent_before_build = []

        with mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ) as mock_notify:
            mock_build_target = (
                "analytics.management.commands.manage_user_requests._build_output"
            )
            with mock.patch(
                mock_build_target,
                side_effect=lambda *a, **k: sent_before_build.append(
                    [call.args[2] for call in mock_notify.call_args_list]
                ),
            ):
                _manage_user_requests()

        # The received email had already been sent when _build_output started.
        self.assertEqual(sent_before_build, [[0]])
        req.refresh_from_db()
        self.assertEqual(req.status, 1)

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
