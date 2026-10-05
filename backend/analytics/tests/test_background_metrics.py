import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from unittest import mock

from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from prometheus_client import CollectorRegistry, REGISTRY

from analytics import background_metrics as bg, metrics
from analytics.management.commands.manage_user_requests import _request_error, RequestClaim
from analytics.models import Request
from analytics.tests.test_metrics import Delta


class JobMetricsTests(SimpleTestCase):
    def test_success_and_exception_keep_result_and_failure_semantics(self):
        success = ("geoquery_background_job_runs_total", (("job_name", "builder"), ("outcome", "success")))
        error = ("geoquery_background_job_runs_total", (("job_name", "builder"), ("outcome", "error")))
        durations = ("geoquery_background_job_seconds_count", (("job_name", "builder"),))
        delta = Delta(success, error, durations)

        @bg.observe_job("builder")
        def job(fail=False):
            if fail:
                raise ValueError("failure")
            return 42

        self.assertEqual(job(), 42)
        timestamp = REGISTRY.get_sample_value(
            "geoquery_background_job_last_success_timestamp_seconds", {"job_name": "builder"},
        )
        with self.assertRaisesMessage(ValueError, "failure"):
            job(True)
        self.assertEqual(delta[success], 1)
        self.assertEqual(delta[error], 1)
        self.assertEqual(delta[durations], 2)
        self.assertEqual(timestamp, REGISTRY.get_sample_value(
            "geoquery_background_job_last_success_timestamp_seconds", {"job_name": "builder"},
        ))

    def test_live_collector_measures_unfinished_chunks_and_zero_when_idle(self):
        registry = CollectorRegistry()
        starts = [100, 120, 0]
        registry.register(metrics.WorkerStateCollector(starts, 1800))
        with mock.patch.object(metrics.time, "monotonic", return_value=200):
            self.assertEqual(registry.get_sample_value("geoquery_extract_oldest_active_chunk_seconds"), 100)
            self.assertEqual(registry.get_sample_value("geoquery_extract_active_chunks"), 2)
            self.assertEqual(registry.get_sample_value("geoquery_extract_slots"), 3)
            starts[:] = [0, 0, 0]
            self.assertEqual(registry.get_sample_value("geoquery_extract_oldest_active_chunk_seconds"), 0)

    def test_multiprocess_metrics_survive_child_exit_and_coexist_with_live_collector(self):
        # Multiprocess mode is selected at import time, so test in fresh
        # interpreters, just as the real parent and children are started.
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": directory}
            child = """
from analytics import background_metrics as bg
bg.JOB_LAST_SUCCESS.labels('builder').set(123)
bg.JOB_RUNS.labels('builder', 'success').inc(2)
"""
            subprocess.run([sys.executable, "-c", child], env=env, check=True, capture_output=True)
            parent = """
from analytics import background_metrics as bg, metrics
from prometheus_client import CollectorRegistry, multiprocess
r = CollectorRegistry()
multiprocess.MultiProcessCollector(r)
r.register(metrics.WorkerStateCollector([0, 0], 1800))
assert r.get_sample_value('geoquery_background_job_last_success_timestamp_seconds', {'job_name': 'builder'}) == 123
assert r.get_sample_value('geoquery_background_job_runs_total', {'job_name': 'builder', 'outcome': 'success'}) == 2
assert r.get_sample_value('geoquery_extract_slots') == 2
"""
            subprocess.run([sys.executable, "-c", parent], env=env, check=True, capture_output=True)


class RequestMetricsTests(TestCase):
    def test_request_completion_and_work_are_recorded_only_on_commit(self):
        count = ("geoquery_request_outcomes_total", (("outcome", "completed"),))
        duration = ("geoquery_request_completion_seconds_sum", ())
        work = ("geoquery_background_work_total", (("operation", "requests_completed"),))
        delta = Delta(count, duration, work)
        now = timezone.now()
        with self.captureOnCommitCallbacks(execute=True), mock.patch.object(timezone, "now", return_value=now):
            bg.record_request_outcome(now - timedelta(seconds=120), "completed")
            self.assertEqual(delta[count], 0)
        self.assertEqual(delta[count], 1)
        self.assertEqual(delta[duration], 120)
        self.assertEqual(delta[work], 1)

    def test_rollback_does_not_emit_completion_or_useful_work(self):
        count = ("geoquery_request_outcomes_total", (("outcome", "completed"),))
        work = ("geoquery_background_work_total", (("operation", "tasks_created"),))
        delta = Delta(count, work)
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValueError), transaction.atomic():
                bg.record_request_outcome(timezone.now(), "completed")
                bg.record_work("tasks_created", 10)
                raise ValueError("rollback")
        self.assertEqual(delta[count], 0)
        self.assertEqual(delta[work], 0)

    def test_lost_claim_and_repeated_failure_do_not_emit_new_failure(self):
        req = Request.objects.create(status=2, data={})
        count = ("geoquery_request_outcomes_total", (("outcome", "failed"),))
        delta = Delta(count)
        with self.captureOnCommitCallbacks(execute=True), self.assertLogs(level="WARNING"):
            _request_error(req.id, "lost", claim=RequestClaim(True, 0, timezone.now(), False))
        self.assertEqual(delta[count], 0)
        with self.captureOnCommitCallbacks(execute=True), self.assertLogs(level="ERROR"):
            _request_error(req.id, "failed")
            _request_error(req.id, "failed again")
        self.assertEqual(delta[count], 1)
