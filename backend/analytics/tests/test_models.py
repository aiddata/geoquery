from django.db import connection
from django.test import TestCase

from analytics.models import ExtractData, ExtractTask


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


class ExtractDataArraysTest(TestCase):
    def test_value_arrays_exist(self):
        field_names = {f.name for f in ExtractData._meta.get_fields()}
        self.assertIn("float_values", field_names)
        self.assertIn("int_values", field_names)
        self.assertIn("str_values", field_names)
        self.assertIn("dataset_id", field_names)
        self.assertNotIn("float_value", field_names)
        self.assertNotIn("int_value", field_names)
        self.assertNotIn("str_value", field_names)

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
