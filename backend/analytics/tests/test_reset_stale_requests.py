import os
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest import mock
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone

from analytics.management.commands.reset_stale_requests import (
    _clean_orphan_output_dirs,
    _redispatch_unmaterialized_requests,
    _reset_stale_requests,
)
from analytics.models import Request


class ResetStaleRequestsTests(TestCase):
    """Recovery for requests stranded at status=2 by a crashed sweep.

    Committing the claim (see the claim/work/finalize split) is what makes
    this necessary: before it, a crash rolled the claim back and the request
    retried naturally. This mirrors free_stale_processing_tasks, which does
    the same job for ExtractTask rows stuck at status=2.
    """

    def make(self, *, status, process_age_minutes=None):
        req = Request.objects.create(contact="a@example.com", status=status, data={})
        if process_age_minutes is not None:
            Request.objects.filter(id=req.id).update(
                process_time=timezone.now() - timedelta(minutes=process_age_minutes)
            )
        return req

    def test_stale_claim_is_reset_to_zero_not_minus_one(self):
        # status=0, not -1: -1 would re-trigger the "request received" email
        # on retry, since send_received_email keys off original_status == -1.
        req = self.make(status=2, process_age_minutes=45)

        result = _reset_stale_requests(30)

        req.refresh_from_db()
        self.assertEqual(req.status, 0)
        self.assertEqual(result["reset"], 1)
        self.assertEqual(result["count"], 1)

    def test_null_process_time_is_reaped(self):
        # NULL < NOW() - INTERVAL is NULL, not true, so a bare comparison
        # would strand a status=2 row whose process_time was never set.
        req = self.make(status=2)
        self.assertIsNone(req.process_time)

        result = _reset_stale_requests(30)

        req.refresh_from_db()
        self.assertEqual(req.status, 0)
        self.assertEqual(result["reset"], 1)

    def test_fresh_claim_is_left_alone(self):
        req = self.make(status=2, process_age_minutes=5)

        result = _reset_stale_requests(30)

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        self.assertEqual(result["reset"], 0)
        self.assertEqual(result["count"], 0)

    def test_other_statuses_are_never_touched(self):
        untouched = [
            self.make(status=s, process_age_minutes=120) for s in (-2, -1, 0, 1, 3, 4)
        ]

        result = _reset_stale_requests(30)

        self.assertEqual(result["reset"], 0)
        for req in untouched:
            before = req.status
            req.refresh_from_db()
            self.assertEqual(req.status, before)

    def test_dry_run_reports_without_changing(self):
        # Both keys are present on both paths so a caller never has to know
        # which path ran; under --dry-run nothing was reset, so reset is 0.
        req = self.make(status=2, process_age_minutes=45)

        result = _reset_stale_requests(30, dry_run=True)

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["reset"], 0)


def _age(path, minutes):
    """Backdate a path's mtime so the reaper considers it abandoned."""
    ts = time.time() - minutes * 60
    # follow_symlinks=False so a dangling symlink can be aged too -- the
    # reaper judges a symlink orphan on the link itself (lstat).
    os.utime(path, (ts, ts), follow_symlinks=not path.is_symlink())


class OrphanOutputCleanupTests(TestCase):
    """The two orphan classes _build_output's swap can leave behind.

    They need opposite treatment and must never be handled by one glob:
    ".building.*" is a half-written build and always disposable, while
    ".replaced.*" can be the ONLY surviving copy of a completed request's
    output (a hard kill between the move-aside and the os.replace leaves
    request_dir absent with the whole output sitting in the aside).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.request_id = str(uuid4())

    def building(self, token=None):
        return self.root / f".{self.request_id}.building.{token or uuid4().hex}"

    def replaced(self, token=None):
        return self.root / f".{self.request_id}.replaced.{token or uuid4().hex}"

    def test_abandoned_building_dir_is_removed(self):
        # A SIGKILL/OOM mid-build leaves both the build directory and its
        # intermediate zip; nothing else collects them.
        build_dir = self.building()
        build_dir.mkdir()
        (build_dir / "partial.csv").write_text("half a build")
        build_zip = Path(str(build_dir) + ".zip")
        build_zip.write_text("half a zip")
        unrelated = self.root / "some-other-request"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("keep")
        _age(build_dir, 120)
        _age(build_zip, 120)
        _age(unrelated, 120)

        result = _clean_orphan_output_dirs(self.root, 30)

        self.assertFalse(build_dir.exists())
        self.assertFalse(build_zip.exists())
        self.assertEqual(result["removed"], 2)
        self.assertTrue((unrelated / "keep.txt").is_file())

    def test_fresh_building_dir_is_left_alone(self):
        # An in-flight build must survive the reaper running alongside it.
        build_dir = self.building()
        build_dir.mkdir()
        (build_dir / "partial.csv").write_text("still being written")

        result = _clean_orphan_output_dirs(self.root, 30)

        self.assertTrue((build_dir / "partial.csv").is_file())
        self.assertEqual(result["removed"], 0)

    def test_replaced_is_restored_when_request_dir_is_missing(self):
        # The case that makes a blanket delete data-destructive: request_dir
        # is gone and the aside holds the completed output a user's "always
        # available" download link points at.
        aside = self.replaced()
        aside.mkdir()
        (aside / f"{self.request_id}.zip").write_text("the only copy")
        _age(aside, 120)

        result = _clean_orphan_output_dirs(self.root, 30)

        request_dir = self.root / self.request_id
        self.assertTrue(request_dir.is_dir())
        self.assertEqual(
            (request_dir / f"{self.request_id}.zip").read_text(), "the only copy"
        )
        self.assertFalse(aside.exists())
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["removed"], 0)

    def test_replaced_is_removed_when_request_dir_exists(self):
        # Something valid supersedes the aside, so it is just garbage.
        request_dir = self.root / self.request_id
        request_dir.mkdir()
        (request_dir / f"{self.request_id}.zip").write_text("current output")
        aside = self.replaced()
        aside.mkdir()
        (aside / f"{self.request_id}.zip").write_text("superseded output")
        _age(request_dir, 120)
        _age(aside, 120)

        result = _clean_orphan_output_dirs(self.root, 30)

        self.assertFalse(aside.exists())
        self.assertEqual(
            (request_dir / f"{self.request_id}.zip").read_text(), "current output"
        )
        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["restored"], 0)

    def test_newest_replaced_is_restored_and_the_rest_removed(self):
        older = self.replaced()
        older.mkdir()
        (older / f"{self.request_id}.zip").write_text("older copy")
        _age(older, 300)
        newer = self.replaced()
        newer.mkdir()
        (newer / f"{self.request_id}.zip").write_text("newer copy")
        _age(newer, 120)

        result = _clean_orphan_output_dirs(self.root, 30)

        request_dir = self.root / self.request_id
        self.assertEqual(
            (request_dir / f"{self.request_id}.zip").read_text(), "newer copy"
        )
        self.assertFalse(older.exists())
        self.assertFalse(newer.exists())
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["removed"], 1)

    def test_non_directory_replaced_is_never_restored(self):
        # A ".replaced." path that is a file or a symlink is not an output
        # tree; restoring it would put an undownloadable thing at the path a
        # download link resolves, and deleting it is not this reaper's call.
        aside = self.replaced()
        aside.symlink_to(self.root / "nowhere")
        _age(aside, 120)

        result = _clean_orphan_output_dirs(self.root, 30)

        self.assertFalse((self.root / self.request_id).exists())
        self.assertTrue(aside.is_symlink())
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["removed"], 0)

    def test_dry_run_changes_nothing(self):
        build_dir = self.building()
        build_dir.mkdir()
        _age(build_dir, 120)
        aside = self.replaced()
        aside.mkdir()
        (aside / f"{self.request_id}.zip").write_text("the only copy")
        _age(aside, 120)

        result = _clean_orphan_output_dirs(self.root, 30, dry_run=True)

        self.assertTrue(build_dir.is_dir())
        self.assertTrue(aside.is_dir())
        self.assertFalse((self.root / self.request_id).exists())
        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["restored"], 1)


class OrphanCollectorLivenessTests(TestCase):
    """A live build's directories must survive the collector.

    Filesystem age cannot express liveness here: a build dir's mtime only
    moves when an entry is created or removed in it, so a long merge (or the
    zip, which is written as a sibling) leaves it frozen; and os.replace does
    not touch mtime at all, so a ".replaced." aside inherits the mtime of the
    output it displaced and is often born already older than the threshold.
    The claim in the database is the signal that actually tracks liveness.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def make_request(self, status):
        return Request.objects.create(
            contact="a@example.com", status=status, data={}
        )

    def age(self, path, minutes=120):
        old = time.time() - minutes * 60
        os.utime(path, (old, old))

    def test_claimed_requests_build_dir_is_not_collected(self):
        req = self.make_request(status=2)
        build = self.root / f".{req.id}.building.{uuid4().hex}"
        build.mkdir()
        (build / "partial.csv").write_text("half a build")
        self.age(build)

        result = _clean_orphan_output_dirs(self.root, 30)

        self.assertEqual(result["removed"], 0)
        self.assertTrue(
            build.is_dir(),
            "the collector deleted a build directory out from under a sweep "
            "that still holds the claim",
        )

    def test_claimed_requests_aside_is_not_collected(self):
        req = self.make_request(status=2)
        aside = self.root / f".{req.id}.replaced.{uuid4().hex}"
        aside.mkdir()
        (aside / "results.csv").write_text("the only copy")
        self.age(aside)

        result = _clean_orphan_output_dirs(self.root, 30)

        self.assertEqual(result, {"removed": 0, "restored": 0})
        self.assertTrue(aside.is_dir())
        self.assertFalse((self.root / str(req.id)).exists())

    def test_unclaimed_requests_orphans_are_still_collected(self):
        # The reset runs before the collector in the same pass, so a dead
        # sweep's request has already left status=2 by now.
        req = self.make_request(status=0)
        build = self.root / f".{req.id}.building.{uuid4().hex}"
        build.mkdir()
        self.age(build)

        result = _clean_orphan_output_dirs(self.root, 30)

        self.assertEqual(result["removed"], 1)
        self.assertFalse(build.exists())


class RedispatchUnmaterializedRequestsTests(TestCase):
    """Recovery for requests stranded at status=4 (materializing).

    materialize_request_tasks turns its own failures into status=-2, so a
    request only sits at 4 when that task never ran at all: the post_save
    signal never fired, or the message was lost (broker outage, or the
    0.43.1 incident where the task wasn't registered and every worker
    dropped it with a KeyError). Nothing else looks at status=4 -- the
    completion sweep selects only -1 and 0 -- so those requests were
    stranded permanently and silently, with the submitter having had a
    confirmation and nothing since.

    Re-dispatching is safe because materialize_request is idempotent by
    design: it deletes any RequestMap rows already attached before
    recreating them, precisely so a re-trigger of a stuck request cannot
    duplicate them.
    """

    def make(self, *, status=4, age_minutes=None):
        req = Request.objects.create(
            contact="a@example.com", status=status, data={}
        )
        if age_minutes is not None:
            Request.objects.filter(id=req.id).update(
                submit_time=timezone.now() - timedelta(minutes=age_minutes)
            )
        return req

    def test_stuck_request_is_redispatched(self):
        req = self.make(age_minutes=90)

        with mock.patch(
            "analytics.tasks.requests.materialize_request_tasks.delay"
        ) as delay:
            result = _redispatch_unmaterialized_requests(30)

        delay.assert_called_once_with(str(req.id))
        self.assertEqual(result["redispatched"], 1)
        req.refresh_from_db()
        self.assertEqual(req.status, 4, "the sweep must not change status itself")

    def test_recent_request_is_left_alone(self):
        # Materialization normally finishes in seconds; a request submitted
        # moments ago is in-flight, not stuck.
        self.make(age_minutes=2)

        with mock.patch(
            "analytics.tasks.requests.materialize_request_tasks.delay"
        ) as delay:
            result = _redispatch_unmaterialized_requests(30)

        delay.assert_not_called()
        self.assertEqual(result["redispatched"], 0)

    def test_other_statuses_are_never_touched(self):
        for status in (-2, -1, 0, 1, 2, 3):
            self.make(status=status, age_minutes=90)

        with mock.patch(
            "analytics.tasks.requests.materialize_request_tasks.delay"
        ) as delay:
            result = _redispatch_unmaterialized_requests(30)

        delay.assert_not_called()
        self.assertEqual(result["redispatched"], 0)

    def test_dry_run_reports_without_dispatching(self):
        self.make(age_minutes=90)

        with mock.patch(
            "analytics.tasks.requests.materialize_request_tasks.delay"
        ) as delay:
            result = _redispatch_unmaterialized_requests(30, dry_run=True)

        delay.assert_not_called()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["redispatched"], 0)

    def test_a_broker_failure_does_not_abort_the_sweep(self):
        # One unreachable broker must not strand every other stuck request;
        # the next hourly pass retries whatever failed.
        first = self.make(age_minutes=90)
        second = self.make(age_minutes=91)

        with mock.patch(
            "analytics.tasks.requests.materialize_request_tasks.delay",
            side_effect=[OSError("broker down"), None],
        ) as delay:
            result = _redispatch_unmaterialized_requests(30)

        self.assertEqual(delay.call_count, 2)
        self.assertEqual(result["redispatched"], 1)
        self.assertEqual(result["failed"], 1)
        for req in (first, second):
            req.refresh_from_db()
            self.assertEqual(req.status, 4)
