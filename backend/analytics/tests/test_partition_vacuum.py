"""Per-partition autovacuum profiles for extract_tasks; see analytics.partition_vacuum."""

from io import StringIO
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import OperationalError, connection
from psycopg import errors
from django.test import SimpleTestCase, TestCase

from analytics.models import ExtractTask, ProcessingOption
from analytics.partition_vacuum import (
    ACTIVE,
    DRAINED,
    _alter,
    _managed,
    reconcile_partition_autovacuum,
)
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection

PENDING, DONE, LOCKED, FAILED = 0, 1, 2, -1


class ReloptionTests(SimpleTestCase):
    def test_managed_ignores_options_it_does_not_own(self):
        self.assertEqual(
            _managed(["fillfactor=90", "autovacuum_vacuum_scale_factor=0.05"]),
            {"autovacuum_vacuum_scale_factor": "0.05"},
        )

    def test_alter_resets_managed_options_the_profile_omits(self):
        stmts = [s.as_string() for s in _alter("extract_tasks_ds_1", ACTIVE)]
        self.assertEqual(stmts, [
            "ALTER TABLE \"extract_tasks_ds_1\" SET (autovacuum_vacuum_scale_factor = '0.05')",
            "ALTER TABLE \"extract_tasks_ds_1\" RESET "
            "(autovacuum_vacuum_threshold, autovacuum_vacuum_cost_limit)",
        ])


class ReconcileTests(TestCase):
    """Runs against real partitions created inside the test transaction."""

    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        cls.resource = DatasetResource.objects.create(
            dataset=cls.dataset, name="ds-2020", path="2020.tif"
        )
        cls.po = ProcessingOption.objects.create(
            dataset=cls.dataset, short_name="mean",
            function="rasterstats_default_mean", active=True,
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        cls.fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))

    def setUp(self):
        self.partition = "extract_tasks_vacuum_test"
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TABLE {self.partition} PARTITION OF extract_tasks "
                "FOR VALUES IN (%s)",
                [self.dataset.id],
            )
        self._seq = 0

    def make_task(self, status):
        self._seq += 1
        task = ExtractTask.objects.create(
            resource_ids=[self.resource.id], dataset_id=self.dataset.id,
            fm=self.fm, po=self.po, status=status, kwargs={"n": self._seq},
        )
        # The FKs are DEFERRABLE INITIALLY DEFERRED and TestCase never
        # commits, so their checks would still be queued when reconcile runs,
        # and Postgres refuses ALTER TABLE on a table with pending trigger
        # events. A real run starts its own transaction with none queued.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        return task

    def reloptions(self, partition=None):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT coalesce(reloptions, '{}') FROM pg_class WHERE relname = %s",
                [partition or self.partition],
            )
            return _managed(cursor.fetchone()[0])

    def test_partition_with_pending_tasks_is_active(self):
        self.make_task(PENDING)
        self.make_task(DONE)
        reconcile_partition_autovacuum()
        self.assertEqual(self.reloptions(), ACTIVE)

    def test_partition_with_running_tasks_stays_active(self):
        # Their completions are still to come; vacuuming now would leave them.
        self.make_task(LOCKED)
        self.make_task(DONE)
        reconcile_partition_autovacuum()
        self.assertEqual(self.reloptions(), ACTIVE)

    def test_partition_with_only_finished_tasks_is_drained(self):
        self.make_task(DONE)
        self.make_task(FAILED)
        reconcile_partition_autovacuum()
        self.assertEqual(self.reloptions(), DRAINED)

    def test_refilled_partition_goes_back_to_active(self):
        self.make_task(DONE)
        reconcile_partition_autovacuum()
        self.make_task(PENDING)
        reconcile_partition_autovacuum()
        self.assertEqual(self.reloptions(), ACTIVE)

    def test_hand_set_overrides_are_replaced(self):
        # ds_23 / ds_24 carried cost_limit=1000 and their own scale factors.
        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE {self.partition} SET (autovacuum_vacuum_cost_limit = 1000,"
                " autovacuum_vacuum_scale_factor = 0.001, fillfactor = 90)"
            )
        self.make_task(PENDING)
        reconcile_partition_autovacuum()
        self.assertEqual(self.reloptions(), ACTIVE)
        with connection.cursor() as cursor:
            cursor.execute("SELECT reloptions FROM pg_class WHERE relname = %s", [self.partition])
            self.assertIn("fillfactor=90", cursor.fetchone()[0])

    def test_second_run_changes_nothing(self):
        self.make_task(PENDING)
        reconcile_partition_autovacuum()
        result = reconcile_partition_autovacuum()
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["unchanged"], result["partitions"])

    def test_default_partition_is_covered(self):
        reconcile_partition_autovacuum()
        self.assertIn(self.reloptions("extract_tasks_default"), (ACTIVE, DRAINED))

    def test_dry_run_alters_nothing(self):
        self.make_task(PENDING)
        out = StringIO()
        call_command("reconcile_partition_autovacuum", "--dry-run", stdout=out)
        self.assertIn(f"{self.partition}: would set active", out.getvalue())
        self.assertEqual(self.reloptions(), {})

    @staticmethod
    def _db_error(cause):
        exc = OperationalError(str(cause))
        exc.__cause__ = cause
        return exc

    def test_lock_timeout_skips_the_partition(self):
        self.make_task(PENDING)
        error = self._db_error(errors.LockNotAvailable("lock timeout"))
        with patch("analytics.partition_vacuum._alter", side_effect=error):
            result = reconcile_partition_autovacuum()
        self.assertGreaterEqual(result["skipped"], 1)
        self.assertNotIn((self.partition, "active"), result["changes"])
        self.assertEqual(self.reloptions(), {})

    def test_other_database_errors_are_not_mistaken_for_lock_timeouts(self):
        self.make_task(PENDING)
        error = self._db_error(errors.ObjectInUse("pending trigger events"))
        with patch("analytics.partition_vacuum._alter", side_effect=error):
            with self.assertRaises(OperationalError):
                reconcile_partition_autovacuum()
