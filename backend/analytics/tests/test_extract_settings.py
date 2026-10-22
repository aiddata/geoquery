"""Extraction settings, the beat schedule and task registration."""

import os
import runpy
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase


def load_settings(**env):
    with mock.patch.dict(os.environ, env):
        return runpy.run_path(str(Path(__file__).resolve().parents[2] / "geoquery" / "settings.py"))


class ExtractSettingsTests(SimpleTestCase):
    def test_defaults(self):
        names = [
            "EXTRACT_TASK_LEASE_PAGE_SIZE", "EXTRACT_TASK_LEASE_BLOCK_SIZE",
            "EXTRACT_TASK_LEASE_SECONDS", "EXTRACT_TASK_LEASE_SCAN_WINDOW",
            "EXTRACT_TASK_LEASE_BISECT_ATTEMPT", "EXTRACT_TASK_LEASE_REPLICA_WAIT_SECONDS",
            "EXTRACT_WORKER_DRAIN_SECONDS", "EXTRACT_COVERAGE_CHUNK_SIZE",
            "EXTRACT_RESET_CHUNK_SIZE", "EXTRACT_SYNC_INTERVAL_SECONDS",
            "EXTRACT_SYNC_CHUNKS_PER_RUN", "EXTRACT_TASK_LEASES_ENABLED",
            "EXTRACT_TASK_LEASE_READ_REPLICA",
        ]
        with mock.patch.dict(os.environ):
            for name in names:
                os.environ.pop(name, None)
            config = load_settings()
        self.assertEqual(
            {name: config[name] for name in names},
            {
                "EXTRACT_TASK_LEASE_PAGE_SIZE": 256, "EXTRACT_TASK_LEASE_BLOCK_SIZE": 256,
                "EXTRACT_TASK_LEASE_SECONDS": 1800, "EXTRACT_TASK_LEASE_SCAN_WINDOW": 100000,
                "EXTRACT_TASK_LEASE_BISECT_ATTEMPT": 3, "EXTRACT_TASK_LEASE_REPLICA_WAIT_SECONDS": 2.0,
                "EXTRACT_WORKER_DRAIN_SECONDS": 840, "EXTRACT_COVERAGE_CHUNK_SIZE": 5000,
                "EXTRACT_RESET_CHUNK_SIZE": 5000, "EXTRACT_SYNC_INTERVAL_SECONDS": 60,
                "EXTRACT_SYNC_CHUNKS_PER_RUN": 20, "EXTRACT_TASK_LEASES_ENABLED": True,
                "EXTRACT_TASK_LEASE_READ_REPLICA": False,
            },
        )

    def test_the_drain_fits_inside_the_lease(self):
        config = load_settings()
        self.assertLess(config["EXTRACT_WORKER_DRAIN_SECONDS"], config["EXTRACT_TASK_LEASE_SECONDS"])

    def test_invalid_limits_are_rejected_at_startup(self):
        for name, value in (
            ("EXTRACT_TASK_LEASE_PAGE_SIZE", "0"),
            ("EXTRACT_TASK_LEASE_SCAN_WINDOW", "-1"),
            ("EXTRACT_SYNC_INTERVAL_SECONDS", "0"),
            ("EXTRACT_RESET_CHUNK_SIZE", "0"),
            ("EXTRACT_TASK_LEASE_BLOCK_SIZE", "512"),
            ("EXTRACT_TASK_LEASE_SECONDS", "60"),
        ):
            with self.subTest(name=name), self.assertRaisesMessage(ImproperlyConfigured, name):
                load_settings(**{name: value})

    def test_the_kill_switch_reads_the_environment(self):
        self.assertFalse(load_settings(EXTRACT_TASK_LEASES_ENABLED="0")["EXTRACT_TASK_LEASES_ENABLED"])

    def test_the_builder_settings_are_gone(self):
        config = load_settings()
        for name in ("N_EXTRACT_TASK_BUILDERS", "EXTRACT_TASK_BUILD_BATCH_SIZE",
                     "EXTRACT_TASK_BUILD_INTERVAL_SECONDS", "EXTRACT_TASK_BUILD_MAX_TASKS",
                     "EXTRACT_TASK_BUILD_SYNCHRONOUS_COMMIT"):
            self.assertNotIn(name, config)


class BeatScheduleTests(SimpleTestCase):
    def test_sync_runs_on_its_interval(self):
        entry = load_settings(EXTRACT_SYNC_INTERVAL_SECONDS="17")["CELERY_BEAT_SCHEDULE"]["sync-extract-work"]
        self.assertEqual(entry["task"], "analytics.tasks.maintenance.sync_extract_work")
        self.assertEqual(entry["schedule"], 17)
        self.assertEqual(entry["options"]["expires"], 17)

    def test_the_builder_and_coverage_entries_are_gone(self):
        schedule = settings.CELERY_BEAT_SCHEDULE
        self.assertNotIn("build-extract-tasks", schedule)
        self.assertNotIn("sweep-coverage-records", schedule)
        for entry in schedule.values():
            self.assertNotIn("build_extract_tasks", entry["task"])
            self.assertNotIn("coverage", entry["task"])

    def test_reapers_and_result_cleanup_are_still_scheduled(self):
        # Without celery-backend-cleanup nothing prunes the result table; it
        # once reached 2.8M rows / 4.4GB in 43 hours.
        schedule = settings.CELERY_BEAT_SCHEDULE
        for name in ("free-stale-processing-tasks", "manage-processing-task-errors",
                     "reset-stale-requests", "celery-backend-cleanup"):
            self.assertIn(name, schedule)
        self.assertGreater(settings.CELERY_RESULT_EXPIRES, 0)

    def test_every_scheduled_task_is_registered(self):
        # A task module missing from analytics/tasks/__init__.py is dropped by
        # every worker with a KeyError (database.md section 8).
        from geoquery.celery import app

        app.loader.import_default_modules()
        registered = set(app.tasks)
        for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
            with self.subTest(name=name):
                self.assertIn(entry["task"], registered)
