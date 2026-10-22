"""Bootstrap of a database created before pair cursor leases."""

import importlib
from types import SimpleNamespace
from datetime import datetime, timezone
from io import StringIO

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, override_settings

from analytics.models import (
    Coverage, CoverageProgress, ExtractInputState, ExtractTask, ExtractTaskBuildProgress,
)
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs
from datasets.models import DatasetResource
from features.models import FeatMap, Feature

migration = importlib.import_module("analytics.migrations.0031_pair_cursor_leases")
UTC = timezone.utc


def state(dataset):
    return ExtractInputState.objects.get(kind="dataset", object_id=dataset.id)


class InitializeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.std, cls.std_po, cls.std_resources = make_dataset("legacy-std", resources=2)
        cls.grp, cls.grp_po, cls.grp_resources = make_dataset("legacy-grp", resources=3, period="year")
        cls.local, cls.local_po, cls.local_resources = make_dataset(
            "legacy-local", is_global=False)
        cls.fc, cls.fms = make_collection("legacy-fc", 3)
        # The state migration 0031 leaves: every pair retired at cursor 0,
        # every dataset dirty and bootstrap-pending.
        ExtractInputState.objects.filter(kind="dataset").update(
            bootstrap_pending=True, generation=1, applied_generation=0, sync_pairs=True,
            rewind_from=0, checkpoint={},
        )
        ExtractInputState.objects.filter(kind="collection").update(
            generation=1, applied_generation=0, rewind_from=0)

        def task(dataset, po, ids, fm, **fields):
            return ExtractTask.objects.create(
                dataset_id=dataset.id, resource_ids=ids, fm=fm, po=po, status=1, **fields)

        cls.std_task = task(cls.std, cls.std_po, [cls.std_resources[0].id], cls.fms[0])
        cls.custom_task = task(cls.std, cls.std_po, [cls.std_resources[0].id], cls.fms[1], kwargs={"k": 1})
        cls.grp_current = task(cls.grp, cls.grp_po, sorted(r.id for r in cls.grp_resources), cls.fms[0])
        cls.grp_obsolete = task(cls.grp, cls.grp_po, sorted(r.id for r in cls.grp_resources[:2]), cls.fms[1])
        cls.grp_request = task(cls.grp, cls.grp_po, [cls.grp_resources[0].id], cls.fms[2], priority=1)
        Coverage.objects.create(geom=cls.fms[0].geom, dataset=cls.local, status=-1)
        Coverage.objects.create(geom=cls.fms[1].geom, dataset=cls.local, status=1)

    def initialize(self, *args):
        out = StringIO()
        call_command("initialize_extract_work", *args, stdout=out)
        return out.getvalue()

    def test_sync_leaves_bootstrap_pending_datasets_alone(self):
        settle_inputs()
        self.assertTrue(state(self.std).bootstrap_pending)
        self.assertFalse(ExtractTaskBuildProgress.objects.filter(dataset_id=self.std.id).exists())

    def test_initialization_backfills_provenance_and_rebuilds_coverage(self):
        self.initialize()
        std_pair = ExtractTaskBuildProgress.objects.get(
            dataset_id=self.std.id, resource_ids=[self.std_resources[0].id], current=True)
        grp_pair = ExtractTaskBuildProgress.objects.get(dataset_id=self.grp.id, current=True)

        def pair_of(task):
            return ExtractTask.objects.get(id=task.id, dataset_id=task.dataset_id).pair_id

        self.assertEqual(pair_of(self.std_task), std_pair.id)
        self.assertIsNone(pair_of(self.custom_task))
        self.assertEqual(pair_of(self.grp_current), grp_pair.id)
        obsolete = ExtractTaskBuildProgress.objects.get(id=pair_of(self.grp_obsolete))
        self.assertFalse(obsolete.current)
        self.assertEqual(obsolete.resource_ids, self.grp_obsolete.resource_ids)
        self.assertIsNone(pair_of(self.grp_request))
        self.assertFalse(Coverage.objects.filter(dataset=self.local).exists())
        for dataset in (self.std, self.grp, self.local):
            self.assertFalse(state(dataset).bootstrap_pending)

        # Ordinary sync then publishes: coverage progress from 0, cursors at 0.
        settle_inputs()
        for dataset in (self.std, self.grp, self.local):
            s = state(dataset)
            self.assertEqual(s.generation, s.applied_generation)
        self.assertEqual(CoverageProgress.objects.get(dataset=self.local).covered_up_to_fm_id, 0)

    def test_running_it_again_changes_nothing(self):
        self.initialize()
        settle_inputs()
        ExtractTaskBuildProgress.objects.filter(current=True).update(cursor_fm_id=7)
        out = self.initialize()
        self.assertIn("0 dataset(s) processed", out)
        self.assertEqual(
            set(ExtractTaskBuildProgress.objects.filter(current=True).values_list("cursor_fm_id", flat=True)),
            {7},
        )

    def test_a_dataset_left_uninitialized_fails_the_command(self):
        DatasetResource.objects.filter(id=self.grp_resources[0].id).update(temporal=None)
        with self.assertRaisesMessage(CommandError, "1 of 3 dataset(s) not initialized"):
            self.initialize()
        self.assertTrue(state(self.grp).bootstrap_pending)
        self.assertFalse(state(self.std).bootstrap_pending)

    @override_settings(EXTRACT_RESET_CHUNK_SIZE=1)
    def test_an_interrupted_run_resumes_from_its_checkpoint(self):
        out = self.initialize("--dataset", str(self.grp.id), "--max-chunks", "2")
        self.assertIn("run again", out)
        checkpoint = state(self.grp).checkpoint["bootstrap"]
        self.assertEqual(checkpoint["phase"], "provenance")
        self.assertTrue(state(self.grp).bootstrap_pending)
        self.initialize("--dataset", str(self.grp.id))
        self.assertFalse(state(self.grp).bootstrap_pending)
        self.assertIsNotNone(
            ExtractTask.objects.get(id=self.grp_obsolete.id, dataset_id=self.grp.id).pair_id)

    def test_an_input_change_mid_initialization_starts_that_dataset_over(self):
        self.initialize("--dataset", str(self.std.id), "--max-chunks", "1")
        self.assertIn("bootstrap", state(self.std).checkpoint)
        DatasetResource.objects.create(dataset=self.std, name="legacy-std-new", path="n.tif")
        self.assertEqual(state(self.std).checkpoint, {})
        self.initialize("--dataset", str(self.std.id))
        self.assertFalse(state(self.std).bootstrap_pending)

    def test_status_lists_what_is_pending(self):
        out = self.initialize("--status")
        self.assertIn(f"dataset {self.std.id}: not started", out)
        self.assertIn("3 dataset(s) pending", out)


class SeedTests(TestCase):
    def test_the_migration_seeds_every_existing_scope_dirty(self):
        dataset, _, _ = make_dataset("seeded")
        fc, _ = make_collection("seeded-fc", 1)
        ExtractInputState.objects.all().delete()
        migration.seed_input_states(None, type("Editor", (), {"connection": connection})())
        d = ExtractInputState.objects.get(kind="dataset", object_id=dataset.id)
        self.assertEqual((d.generation, d.applied_generation, d.bootstrap_pending, d.sync_pairs, d.rewind_from),
                         (1, 0, True, True, 0))
        c = ExtractInputState.objects.get(kind="collection", object_id=fc.id)
        self.assertEqual((c.generation, c.applied_generation, c.bootstrap_pending), (1, 0, False))

    def test_the_migration_left_bigint_ids_and_an_unlimited_sequence(self):
        with connection.cursor() as cursor:
            for table, column in migration.TASK_ID_COLUMNS:
                with self.subTest(f"{table}.{column}"):
                    self.assertEqual(migration._coltype(cursor, table, column), "bigint")
            cursor.execute(
                "SELECT max_value FROM pg_sequences "
                "WHERE schemaname || '.' || sequencename = pg_get_serial_sequence('extract_tasks', 'id')"
            )
            self.assertEqual(cursor.fetchone()[0], 9_223_372_036_854_775_807)

    def test_task_ids_past_int4_flow_through_claims_and_leases(self):
        from analytics.tasks.processing import _release_claimed_tasks

        self.assertEqual(_release_claimed_tasks([(2_147_483_648, 1)]), 0)
        dataset, po, (resource,) = make_dataset("big-ids")
        _, (fm,) = make_collection("big-ids-fc", 1)
        task = ExtractTask.objects.create(
            id=3_000_000_000, dataset_id=dataset.id, resource_ids=[resource.id], fm=fm, po=po)
        self.assertEqual(ExtractTask.objects.get(id=task.id, dataset_id=dataset.id).id, 3_000_000_000)


class IndexReorderTests(TestCase):
    """Migration 0031's index step, when the new index was built beforehand."""

    editor = SimpleNamespace(connection=connection, quote_name=connection.ops.quote_name)

    def indexes(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'extract_tasks'")
            return {r[0] for r in cursor.fetchall()}

    def test_a_prebuilt_index_still_drops_the_old_ones_and_the_po_key(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE INDEX extract_tasks_po_id_idx ON extract_tasks (po_id);
                CREATE UNIQUE INDEX extract_tasks_fm_po_resources_null_kwargs_idx
                    ON extract_tasks (dataset_id, fm_id, po_id, resource_ids_hash) WHERE kwargs IS NULL;
                ALTER TABLE extract_tasks ADD CONSTRAINT extract_tasks_po_id_fkey
                    FOREIGN KEY (po_id) REFERENCES processing_options (id) DEFERRABLE INITIALLY DEFERRED;
                """
            )
        migration.reorder_unique_index(None, self.editor)
        indexes = self.indexes()
        self.assertIn("extract_tasks_pair_null_kwargs_idx", indexes)
        self.assertFalse({"extract_tasks_po_id_idx", "extract_tasks_fm_po_resources_null_kwargs_idx"} & indexes)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_constraint WHERE conrelid = 'extract_tasks'::regclass "
                "AND confrelid = 'processing_options'::regclass"
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_an_invalid_prebuilt_index_is_refused(self):
        # Built ON ONLY the parent and never attached to the partitions'.
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DROP INDEX extract_tasks_pair_null_kwargs_idx;
                CREATE UNIQUE INDEX extract_tasks_pair_null_kwargs_idx
                    ON ONLY extract_tasks (dataset_id, po_id, resource_ids_hash, fm_id)
                    WHERE kwargs IS NULL;
                CREATE INDEX extract_tasks_po_id_idx ON extract_tasks (po_id);
                """
            )
        with self.assertRaisesMessage(RuntimeError, "is invalid"):
            migration.reorder_unique_index(None, self.editor)
        self.assertIn("extract_tasks_po_id_idx", self.indexes())
