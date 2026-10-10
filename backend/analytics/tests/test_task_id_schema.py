"""Task-id columns are bigint end to end.

The test database is built by migrations, so this also covers migration
0031's in-place path -- the one every fresh, development and CI database takes.
"""

from django.db import connection
from django.test import TestCase

INT8_MAX = 9_223_372_036_854_775_807


def _coltype(table, column):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = %s::regclass AND attname = %s",
            [table, column],
        )
        return cursor.fetchone()[0]


class TaskIdSchemaTests(TestCase):
    def test_every_task_id_column_is_bigint(self):
        for table, column in (
            ("extract_tasks", "id"),
            ("extract_data", "extract_task_id"),
            ("request_map", "task_id"),
        ):
            with self.subTest(f"{table}.{column}"):
                self.assertEqual(_coltype(table, column), "bigint")

    def test_identity_sequence_reaches_the_bigint_range(self):
        # Widening an identity column leaves its sequence's MAXVALUE where it
        # was. Without the explicit SET MAXVALUE the column would be bigint
        # and ids would still stop at int4's maximum.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT data_type::text, max_value FROM pg_sequences "
                "WHERE schemaname || '.' || sequencename = pg_get_serial_sequence('extract_tasks', 'id')"
            )
            data_type, max_value = cursor.fetchone()
        self.assertEqual(data_type, "bigint")
        self.assertEqual(max_value, INT8_MAX)

    def test_partitions_follow_the_parent(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT format_type(a.atttypid, a.atttypmod) FROM pg_inherits i "
                "JOIN pg_attribute a ON a.attrelid = i.inhrelid AND a.attname = 'id' "
                "WHERE i.inhparent = 'extract_tasks'::regclass"
            )
            self.assertEqual([r[0] for r in cursor.fetchall()], ["bigint"])
