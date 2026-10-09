"""Task ids past int4's range: the SQL that carries them, and the converter.

extract_tasks_id_seq ran out at 2,147,483,647; see database.md section 11.
"""

from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase

from analytics.management.commands.convert_task_ids_to_bigint import _bound_check

INT4_MAX = 2_147_483_647


class IdArrayTests(TestCase):
    def test_release_accepts_ids_past_int4(self):
        # Exercises the real statement. With the id array cast to int[] this
        # raises "integer out of range"; with bigint[] it simply matches
        # nothing -- and does so against an int4 column too, which is what
        # lets this ship before the column conversion.
        from analytics.tasks.processing import _release_claimed_tasks

        self.assertEqual(_release_claimed_tasks([(INT4_MAX + 1, 1)]), 0)

    def test_every_id_array_is_cast_to_bigint(self):
        # The claim, release, persist and extract_data-delete statements all
        # unnest (dataset_id, id) pairs; none may narrow the id.
        import inspect

        from analytics.tasks import processing

        source = inspect.getsource(processing)
        self.assertNotIn("%s::int[], %s::int[]", source)
        self.assertEqual(source.count("%s::int[], %s::bigint[]"), 4)


class BoundCheckTests(SimpleTestCase):
    """The CHECK added during each partition's rewrite must imply its bound.

    That implication is what lets ATTACH skip a validation scan of the whole
    partition, so a CHECK that is merely compatible is not good enough.
    """

    def test_single_value(self):
        self.assertEqual(_bound_check("FOR VALUES IN (23)"),
                         "dataset_id IS NOT NULL AND dataset_id IN (23)")

    def test_several_values(self):
        self.assertEqual(_bound_check("FOR VALUES IN (1, 2)"),
                         "dataset_id IS NOT NULL AND dataset_id IN (1, 2)")

    def test_default_partition_gets_no_check(self):
        self.assertIsNone(_bound_check("DEFAULT"))

    def test_unexpected_bound_refuses(self):
        with self.assertRaises(CommandError):
            _bound_check("FOR VALUES FROM (1) TO (5)")
