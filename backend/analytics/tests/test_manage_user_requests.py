import errno
import os
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

            # _build_output assembles everything in a temporary directory,
            # zips it, moves the zip in under the request-id name, and only
            # then renames the whole directory onto request_dir. However it is
            # built, the artifact has to end up at
            # request_dir/request_id.zip -- the path _notify_user's completion
            # email and DocBuilder's download link point at.
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

    def make_previous_output(self, tmp, request_id):
        """Stand in for a request that was already built once and downloaded."""
        request_dir = Path(tmp) / request_id
        request_dir.mkdir(parents=True)
        (request_dir / f"{request_id}.zip").write_bytes(b"previous output")
        return request_dir

    def assert_previous_output_survived(self, tmp, request_id):
        request_dir = Path(tmp) / request_id
        self.assertTrue(request_dir.is_dir())
        self.assertEqual(
            (request_dir / f"{request_id}.zip").read_bytes(), b"previous output"
        )
        # Restored in place, not left lying around under a temp name.
        self.assertEqual(
            [p.name for p in Path(tmp).iterdir()], [request_id]
        )

    def prepare(self):
        """A materialized request with finished tasks, ready to build."""
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
        return created.request, task_map

    def assert_surviving_output_is_one_whole_build(
        self, tmp, request_id, markers=()
    ):
        """Assert request_dir holds one whole build rather than a mix of two.

        Names alone cannot show that, since every build emits the same
        filenames: a directory holding one build's CSV beside another's HTML
        passes any name-based check. So every zip entry is also compared
        byte-for-byte with the file sitting beside it, and when `markers` are
        given (each build's download_server, which DocBuilder writes into the
        documentation HTML) exactly one of them may appear anywhere in the
        surviving output.
        """
        request_dir = Path(tmp) / request_id
        output_zip = request_dir / f"{request_id}.zip"
        self.assertTrue(output_zip.is_file())
        # No build directory, displaced directory or stray zip left over.
        self.assertEqual(
            [p.name for p in Path(tmp).iterdir() if p.name != request_id], []
        )

        with zipfile.ZipFile(output_zip) as zf:
            self.assertIsNone(zf.testzip())
            zipped = {name: zf.read(name) for name in zf.namelist()}

        # No zip nested inside the zip from the other build.
        self.assertNotIn(f"{request_id}.zip", zipped)
        on_disk = {p.name for p in request_dir.iterdir()}
        self.assertEqual(
            set(zipped) - {"GeoQuery_Goodman2019.pdf"},
            on_disk - {f"{request_id}.zip"},
        )

        for name, zipped_bytes in zipped.items():
            if name == "GeoQuery_Goodman2019.pdf":
                continue  # deleted from the directory after zipping
            self.assertEqual(
                zipped_bytes,
                (request_dir / name).read_bytes(),
                f"{name} in the zip differs from the one beside it",
            )

        if markers:
            blobs = list(zipped.values()) + [
                p.read_bytes() for p in request_dir.iterdir()
            ]
            found = {
                marker
                for marker in markers
                if any(marker.encode() in blob for blob in blobs)
            }
            self.assertEqual(
                len(found),
                1,
                f"expected output from exactly one build, found {found}",
            )

    def test_failed_build_keeps_the_previous_output(self):
        # A rebuild that dies partway must leave the previously built output
        # downloadable. The test above only proves no *partial* directory is
        # created; this one proves an existing one is not destroyed, which is
        # what building in place got wrong.
        with tempfile.TemporaryDirectory() as tmp:
            request, task_map = self.prepare()
            request_id = str(request.id)
            self.make_previous_output(tmp, request_id)

            with mock.patch.object(
                mur, "DocBuilder", side_effect=RuntimeError("boom")
            ):
                with self.assertRaises(RuntimeError):
                    _build_output(request, task_map, "", tmp, "../assets")

            self.assert_previous_output_survived(tmp, request_id)

    def test_failed_swap_keeps_the_previous_output(self):
        # The swap displaces the old output before landing the new one, so a
        # swap that then fails is the one path where the displaced copy is
        # the *only* copy. It has to be put back: deleting it would leave
        # request_dir absent entirely, losing output the user could download
        # a moment ago -- worse than the failed rebuild itself.
        #
        # Persistent ENOTEMPTY (an NFS silly-rename file, say) stands in for
        # any swap that cannot complete; move-aside and restore still work.
        with tempfile.TemporaryDirectory() as tmp:
            request, task_map = self.prepare()
            request_id = str(request.id)
            self.make_previous_output(tmp, request_id)

            real_replace = os.replace

            def build_never_lands(src, dst, *args, **kwargs):
                if ".building." in str(src):
                    raise OSError(errno.ENOTEMPTY, "Directory not empty")
                return real_replace(src, dst, *args, **kwargs)

            with mock.patch("os.replace", build_never_lands):
                with self.assertRaises(OSError) as raised:
                    _build_output(request, task_map, "", tmp, "../assets")

            self.assertEqual(raised.exception.errno, errno.ENOTEMPTY)
            self.assert_previous_output_survived(tmp, request_id)

    def test_unretryable_swap_failure_is_not_retried(self):
        # Only "destination is a non-empty directory" is worth retrying --
        # that is the failure another build causes and a retry fixes. A
        # permissions failure will not fix itself, and every retry displaces
        # the old output again, so it must propagate on the first attempt.
        with tempfile.TemporaryDirectory() as tmp:
            request, task_map = self.prepare()
            request_id = str(request.id)
            self.make_previous_output(tmp, request_id)

            real_replace = os.replace
            attempts = []

            def build_never_lands(src, dst, *args, **kwargs):
                if ".building." in str(src):
                    attempts.append(str(dst))
                    raise OSError(errno.EACCES, "Permission denied")
                return real_replace(src, dst, *args, **kwargs)

            with mock.patch("os.replace", build_never_lands):
                with self.assertRaises(PermissionError):
                    _build_output(request, task_map, "", tmp, "../assets")

            self.assertEqual(len(attempts), 1)
            self.assert_previous_output_survived(tmp, request_id)

    def test_interleaved_builds_do_not_corrupt_each_other(self):
        # Once a reaper can reset a claim out from under a running build, two
        # sweeps can be inside _build_output for the same request at the same
        # time. Rather than threads, run a second build to completion from
        # inside the first one's DocBuilder step -- the same interleaving,
        # deterministically. Both must finish, and the surviving directory
        # must be one build's output rather than a mix.
        with tempfile.TemporaryDirectory() as tmp:
            request, task_map = self.prepare()
            request_id = str(request.id)

            # Each build stamps its own download_server into the generated
            # HTML, so a directory mixing the two is detectable by content.
            outer, inner = "http://outer-build", "http://inner-build"
            real_doc_builder = mur.DocBuilder
            state = {"nested_done": False}

            def build_concurrently(*args, **kwargs):
                if not state["nested_done"]:
                    state["nested_done"] = True
                    _build_output(request, task_map, inner, tmp, "../assets")
                return real_doc_builder(*args, **kwargs)

            with mock.patch.object(
                mur, "DocBuilder", side_effect=build_concurrently
            ):
                _build_output(request, task_map, outer, tmp, "../assets")

            self.assertTrue(state["nested_done"])
            self.assert_surviving_output_is_one_whole_build(
                tmp, request_id, markers=(outer, inner)
            )

    def test_build_losing_the_swap_returns_instead_of_raising(self):
        # The test above serializes the two builds -- the inner one finishes
        # its swap before the outer resumes -- so it never overlaps the swap
        # itself. Do that here: suspend one build inside its swap, at the
        # os.replace that targets request_dir, and let a second build run all
        # the way through that same region before the first resumes. That is
        # the window where the loser's replace finds a repopulated
        # request_dir.
        #
        # It must not raise. A sweep that still holds its claim and raises
        # here passes _request_error's fence and marks the request failed --
        # even though its build produced complete, valid output and only lost
        # a race to write it into place.
        with tempfile.TemporaryDirectory() as tmp:
            request, task_map = self.prepare()
            request_id = str(request.id)
            request_dir = Path(tmp) / request_id

            outer, inner = "http://outer-build", "http://inner-build"
            real_replace = os.replace
            state = {"nested_done": False}

            def replace_after_concurrent_build(src, dst, *args, **kwargs):
                if not state["nested_done"] and str(dst) == str(request_dir):
                    state["nested_done"] = True
                    # A second sweep lands its own finished output at
                    # request_dir in exactly the window this build is
                    # standing in.
                    _build_output(request, task_map, inner, tmp, "../assets")
                return real_replace(src, dst, *args, **kwargs)

            with mock.patch("os.replace", replace_after_concurrent_build):
                _build_output(request, task_map, outer, tmp, "../assets")

            # Guards against the test going vacuous if the swap is reworked
            # and never renames onto request_dir again.
            self.assertTrue(state["nested_done"])
            self.assert_surviving_output_is_one_whole_build(
                tmp, request_id, markers=(outer, inner)
            )

    def test_output_replaces_a_request_dir_that_is_a_file(self):
        # ENOTDIR is one of the retryable errnos precisely because
        # request_dir can exist as a file or symlink. Displacing it then
        # leaves a *file* named .{id}.replaced.{hex}, which rmtree silently
        # ignores -- so the swap has to clean up by the right mechanism or it
        # litters the requests directory on every rebuild.
        with tempfile.TemporaryDirectory() as tmp:
            request, task_map = self.prepare()
            request_id = str(request.id)
            (Path(tmp) / request_id).write_text("not a directory")

            _build_output(request, task_map, "", tmp, "../assets")

            self.assert_surviving_output_is_one_whole_build(tmp, request_id)

    def test_rebuild_survives_sustained_contention(self):
        # A rebuild over existing output always spends one pass discovering
        # request_dir is occupied and displacing it. That expected pass must
        # not eat into the budget for *contention*, or a build whose output is
        # complete raises under a concurrent rebuild and its caller records
        # status=-2 for a request whose directory holds a valid build.
        #
        # Pin the budget: existing output, then a concurrent build
        # repopulating request_dir on every attempt until the budget is spent.
        with tempfile.TemporaryDirectory() as tmp:
            request, task_map = self.prepare()
            request_id = str(request.id)
            request_dir = self.make_previous_output(tmp, request_id)

            real_replace = os.replace
            contention = [None] * mur._OUTPUT_SWAP_CONTENTION_RETRIES

            def repopulate_then_replace(src, dst, *args, **kwargs):
                if ".building." in str(src) and contention:
                    # Another build lands its output just before ours does.
                    contention.pop()
                    request_dir.mkdir(parents=True, exist_ok=True)
                    (request_dir / "other_build.txt").write_text("other")
                return real_replace(src, dst, *args, **kwargs)

            with mock.patch("os.replace", repopulate_then_replace):
                _build_output(request, task_map, "", tmp, "../assets")

            # The budget was actually exercised, and the build still landed.
            self.assertEqual(contention, [])
            self.assert_surviving_output_is_one_whole_build(tmp, request_id)


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
        # ones. Cross-connection commit visibility is not covered anywhere
        # yet -- it needs a TransactionTestCase, which a later task in this
        # plan is expected to add.
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

    def test_lost_claim_does_not_mark_the_request_failed(self):
        # Same takeover as above, but the stale sweep then *raises*. Its error
        # handler must not flip the request to -2: the new owner is mid-build
        # (status=2), and in the worst case has already completed the request
        # and emailed a download link. The claim fence is what tells a real
        # failure apart from a stale sweep's.
        req = self.submit()
        ExtractTask.objects.update(status=1)

        def takeover_then_fail(*args, **kwargs):
            Request.objects.filter(id=req.id).update(
                status=2, process_time=timezone.now()
            )
            raise RuntimeError("boom")

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output",
            side_effect=takeover_then_fail,
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        req.refresh_from_db()
        # The new owner's claim stands; the stale sweep's error was dropped.
        self.assertEqual(req.status, 2)

    def test_held_claim_still_marks_the_request_failed(self):
        # The fence must not swallow real failures: a sweep that still owns
        # its claim and raises records the error exactly as it always has.
        req = self.submit()
        ExtractTask.objects.update(status=1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output",
            side_effect=RuntimeError("boom"),
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        req.refresh_from_db()
        self.assertEqual(req.status, -2)

    def submit_invalid(self, invalid):
        """A queued request that fails one of the three validation checks."""
        req = self.submit()
        data = {} if invalid == "data" else dict(req.data, **{invalid: []})
        Request.objects.filter(id=req.id).update(data=data)
        return req

    def test_validation_failures_still_mark_the_request_failed(self):
        # The validation failures fire before any claim exists, so
        # _request_error has nothing to fence on and must behave as before.
        # Guards against the optional fence being made mandatory.
        for invalid in ("data", "feature_ids", "datasets"):
            with self.subTest(invalid=invalid):
                req = self.submit_invalid(invalid)

                with mock.patch(
                    "analytics.management.commands.manage_user_requests._notify_user"
                ):
                    _manage_user_requests()

                req.refresh_from_db()
                self.assertEqual(req.status, -2)
                # Never claimed -- the error was written with no claim.
                self.assertIsNone(req.process_time)

    def test_dry_run_writes_no_status_for_validation_failures(self):
        # --dry-run advertises "without making any changes to the database",
        # and these three sites are the ones that fire before a claim exists.
        # Each could permanently move a real queued request from -1 to -2.
        for invalid in ("data", "feature_ids", "datasets"):
            with self.subTest(invalid=invalid):
                req = self.submit_invalid(invalid)

                with mock.patch(
                    "analytics.management.commands.manage_user_requests._notify_user"
                ):
                    _manage_user_requests(dry_run=True)

                req.refresh_from_db()
                self.assertEqual(req.status, -1)

    def test_error_before_a_claim_ignores_the_previous_requests_claim(self):
        # The claim the error fence uses is per-iteration. `claim` itself is a
        # loop local that survives into the next iteration, so a request that
        # fails *before* claiming must not have its error write fenced on the
        # previous request's claim_time -- that would silently drop it and
        # leave the request sitting in the queue forever.
        first = self.submit()
        second = self.submit()
        # The sweep orders by -priority then submit_time; distinct priorities
        # pin "first is processed first" rather than leaning on two
        # timestamps that could tie.
        Request.objects.filter(id=first.id).update(priority=1)
        Request.objects.filter(id=second.id).update(priority=0)
        ExtractTask.objects.update(status=1)
        data = dict(second.data)
        del data["feature_ids"]
        Request.objects.filter(id=second.id).update(data=data)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        first.refresh_from_db()
        second.refresh_from_db()
        # The first request claimed and completed, so a stale claim exists.
        self.assertEqual(first.status, 1)
        # The second failed before claiming and must still be marked failed.
        self.assertEqual(second.status, -2)
        self.assertIsNone(second.process_time)

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

    def test_dry_run_writes_no_status_when_the_build_fails(self):
        # "No status writes at all" has to hold on the error path too: a dry
        # run that hits an exception must not park a real request at -2.
        req = self.submit()
        ExtractTask.objects.update(status=1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output",
            side_effect=RuntimeError("boom"),
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests(dry_run=True)

        req.refresh_from_db()
        self.assertEqual(req.status, -1)
