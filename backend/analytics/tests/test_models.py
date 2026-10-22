from django.contrib.gis.geos import Point
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TestCase

from analytics.models import (
    ExtractData,
    ExtractTask,
    ExtractTaskBuildProgress,
    ProcessingOption,
    Request,
    RequestMap,
)
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection


class ExtractTaskResourceIdsTest(TestCase):
    def test_resource_ids_is_postgres_array(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT data_type, udt_name FROM information_schema.columns
                WHERE table_name = 'extract_tasks' AND column_name = 'resource_ids'
            """)
            row = cursor.fetchone()
        self.assertIsNotNone(row, "resource_ids column does not exist")
        self.assertEqual(row[0], "ARRAY")
        self.assertEqual(row[1], "_int4")

    def test_resource_field_removed_and_new_fields_present(self):
        field_names = {f.name for f in ExtractTask._meta.get_fields()}
        self.assertNotIn("resource", field_names)
        self.assertIn("resource_ids", field_names)
        self.assertIn("dataset_id", field_names)
        self.assertIn("task_group_period", field_names)


class ExtractTaskResourceIdsHashTest(TestCase):
    def test_resource_ids_hash_column_exists_and_generated(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT data_type, is_generated FROM information_schema.columns
                WHERE table_name = 'extract_tasks' AND column_name = 'resource_ids_hash'
            """)
            row = cursor.fetchone()
        self.assertIsNotNone(row, "resource_ids_hash column does not exist")
        self.assertEqual(row[0], "integer")
        self.assertEqual(row[1], "ALWAYS")

    def test_resource_ids_hash_matches_hashtext_of_array(self):
        dataset = Dataset.objects.create(name="hashtest", path="hashtest", active=True)
        resource = DatasetResource.objects.create(dataset=dataset, name="r1", path="r1.tif")
        po = ProcessingOption.objects.create(
            dataset=dataset, short_name="mean", function="rasterstats_default_mean", active=True
        )
        fc = FeatureCollection.objects.create(name="fc-hash", path="/data/fc-hash", active=True)
        feat = Feature.objects.create(shape=Point(0, 0))
        fm = FeatMap.objects.create(fc=fc, geom=feat)

        task = ExtractTask.objects.create(
            dataset_id=dataset.id, resource_ids=[resource.id], fm=fm, po=po,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT hashtext(%s::text)", [[resource.id]])
            expected_hash = cursor.fetchone()[0]

        task.refresh_from_db()
        self.assertEqual(task.resource_ids_hash, expected_hash)

    def test_unique_indexes_use_hash_column(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname, indexdef FROM pg_indexes
                WHERE tablename = 'extract_tasks'
                  AND indexname IN (
                      'extract_tasks_pair_null_kwargs_idx',
                      'extract_tasks_fm_po_resources_kwargs_hash_idx'
                  )
            """)
            defs = dict(cursor.fetchall())
        self.assertEqual(len(defs), 2)
        for indexdef in defs.values():
            self.assertIn("resource_ids_hash", indexdef)
            self.assertNotIn("resource_ids)", indexdef)
        # Migration 0031: fm_id last, the order a lease page inserts in.
        self.assertIn(
            "(dataset_id, po_id, resource_ids_hash, fm_id) WHERE (kwargs IS NULL)",
            defs["extract_tasks_pair_null_kwargs_idx"],
        )

    def test_old_unique_and_po_indexes_are_gone(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'extract_tasks'
                  AND indexname IN (
                      'extract_tasks_fm_po_resources_null_kwargs_idx',
                      'extract_tasks_po_id_idx'
                  )
            """)
            self.assertEqual(cursor.fetchall(), [])


class ExtractDataArraysTest(TestCase):
    def test_value_arrays_exist(self):
        # Both sides of the row exist: scalars for single-resource tasks,
        # arrays for grouped ones. A row populates one side or the other.
        field_names = {f.name for f in ExtractData._meta.get_fields()}
        self.assertIn("float_values", field_names)
        self.assertIn("int_values", field_names)
        self.assertIn("str_values", field_names)
        self.assertIn("dataset_id", field_names)
        self.assertIn("float_value", field_names)
        self.assertIn("int_value", field_names)
        self.assertIn("str_value", field_names)

    def test_value_array_columns_are_postgres_arrays(self):
        from django.db import connection
        with connection.cursor() as cursor:
            for col, udt in [("float_values", "_float8"), ("int_values", "_int8"), ("str_values", "_varchar")]:
                cursor.execute("""
                    SELECT data_type, udt_name FROM information_schema.columns
                    WHERE table_name = 'extract_data' AND column_name = %s
                """, [col])
                row = cursor.fetchone()
                self.assertIsNotNone(row, f"{col} column does not exist")
                self.assertEqual(row[0], "ARRAY", f"{col} is not an array type")
                self.assertEqual(row[1], udt, f"{col} has unexpected udt_name {row[1]}")

    def test_scalar_value_columns_match_their_array_element_types(self):
        # A scalar column whose type drifts from its array counterpart would
        # silently truncate or overflow once the writer starts choosing
        # between the two paths per row.
        from django.db import connection
        with connection.cursor() as cursor:
            for col, udt in [("float_value", "float8"), ("int_value", "int8"), ("str_value", "varchar")]:
                cursor.execute("""
                    SELECT udt_name FROM information_schema.columns
                    WHERE table_name = 'extract_data' AND column_name = %s
                """, [col])
                row = cursor.fetchone()
                self.assertIsNotNone(row, f"{col} missing from extract_data")
                self.assertEqual(row[0], udt, f"{col} has unexpected udt_name {row[0]}")

    def test_composite_primary_key_at_db_level(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON kcu.constraint_name = tc.constraint_name
                    AND kcu.table_name = tc.table_name
                WHERE tc.table_name = 'extract_data' AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
            """)
            pk_columns = [row[0] for row in cursor.fetchall()]
        self.assertEqual(pk_columns, ["dataset_id", "extract_task_id", "name"])

    def test_id_column_removed(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT count(*) FROM information_schema.columns
                WHERE table_name = 'extract_data' AND column_name = 'id'
            """)
            count = cursor.fetchone()[0]
        self.assertEqual(count, 0, "id column should be removed")

    def test_name_is_not_null_at_db_level(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT is_nullable FROM information_schema.columns
                WHERE table_name = 'extract_data' AND column_name = 'name'
            """)
            is_nullable = cursor.fetchone()[0]
        self.assertEqual(is_nullable, "NO")


class ExtractTaskPendingIdxTiebreakerTest(TestCase):
    def test_pending_idx_includes_id_column(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexdef FROM pg_indexes
                WHERE tablename = 'extract_tasks' AND indexname = 'extract_tasks_pending_idx'
            """)
            row = cursor.fetchone()
        self.assertIsNotNone(row, "extract_tasks_pending_idx does not exist")
        self.assertIn("id", row[0].split("(")[1].split(")")[0])


class ExtractTaskBuildProgressArrayTest(TestCase):
    def test_resource_ids_array(self):
        field_names = {f.name for f in ExtractTaskBuildProgress._meta.get_fields()}
        self.assertIn("resource_ids", field_names)
        self.assertNotIn("resource", field_names)

    def test_resource_ids_is_postgres_array_at_db_level(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT data_type, udt_name FROM information_schema.columns
                WHERE table_name = 'extract_task_build_progress' AND column_name = 'resource_ids'
            """)
            row = cursor.fetchone()
        self.assertIsNotNone(row, "resource_ids column does not exist")
        self.assertEqual(row[0], "ARRAY")
        self.assertEqual(row[1], "_int4")

    def test_unique_constraint_on_resource_ids_and_po(self):
        constraint_names = {
            c.name for c in ExtractTaskBuildProgress._meta.constraints
        }
        self.assertIn(
            "extract_task_build_progress_resource_ids_po_unique", constraint_names
        )

    def test_unique_constraint_exists_at_db_level(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT contype FROM pg_constraint
                WHERE conname = 'extract_task_build_progress_resource_ids_po_unique'
            """)
            row = cursor.fetchone()
        self.assertIsNotNone(row, "constraint does not exist in the database")
        self.assertEqual(row[0], "u")


class ProcessingOptionDeleteTests(TestCase):
    """extract_tasks has no po_id index or foreign key (migration 0031)."""

    def setUp(self):
        from analytics.tests.extract_helpers import make_collection, make_dataset

        self.dataset, self.po, (resource,) = make_dataset("po-delete")
        self.other, other_po, (other_resource,) = make_dataset("po-keep")
        _, fms = make_collection("po-delete-fc", 2)
        for fm in fms:
            ExtractTask.objects.create(
                dataset_id=self.dataset.id, resource_ids=[resource.id], fm=fm, po=self.po)
            ExtractTask.objects.create(
                dataset_id=self.other.id, resource_ids=[other_resource.id], fm=fm, po=other_po)
        # Results and request links go with their task (checked at teardown,
        # when the deferred constraints are).
        doomed = ExtractTask.objects.filter(dataset_id=self.dataset.id).first()
        ExtractData.objects.create(
            extract_task=doomed, dataset_id=self.dataset.id, name="mean", float_values=[1.0])
        request = Request.objects.create(contact="a@b.c", status=-1, data={})
        RequestMap.objects.create(request=request, task=doomed, dataset_id=self.dataset.id)

    def assert_partition_pruned(self, context):
        queries = [q["sql"] for q in context.captured_queries if "extract_tasks" in q["sql"]]
        self.assertTrue(queries)
        for sql in queries:
            self.assertIn("dataset_id", sql)

    def test_deleting_an_option_deletes_its_tasks_within_its_partition(self):
        with CaptureQueriesContext(connection) as context:
            self.po.delete()
        self.assertFalse(ExtractTask.objects.filter(dataset_id=self.dataset.id).exists())
        self.assertFalse(ExtractData.objects.filter(dataset_id=self.dataset.id).exists())
        self.assertFalse(RequestMap.objects.filter(dataset_id=self.dataset.id).exists())
        self.assertEqual(ExtractTask.objects.filter(dataset_id=self.other.id).count(), 2)
        self.assert_partition_pruned(context)

    def test_deleting_a_dataset_deletes_its_tasks_within_its_partition(self):
        with CaptureQueriesContext(connection) as context:
            self.dataset.delete()
        self.assertFalse(ExtractTask.objects.filter(dataset_id=self.dataset.id).exists())
        self.assertEqual(ExtractTask.objects.filter(dataset_id=self.other.id).count(), 2)
        self.assert_partition_pruned(context)
