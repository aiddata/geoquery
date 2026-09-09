from django.db import connection
from django.test import TestCase

from analytics.models import ExtractTask


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
