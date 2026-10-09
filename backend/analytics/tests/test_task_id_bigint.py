"""Task ids past int4's range in the SQL that carries them.

extract_tasks_id_seq ran out at 2,147,483,647; every task id after it is
larger, so no statement may narrow an id to int4.
"""

import inspect

from django.test import TestCase

INT4_MAX = 2_147_483_647


class IdArrayTests(TestCase):
    def test_release_accepts_ids_past_int4(self):
        # Exercises the real statement. With the id array cast to int[] this
        # raises "integer out of range"; with bigint[] it simply matches
        # nothing -- and does so against an int4 column too, which is what
        # lets this ship independently of the column conversion.
        from analytics.tasks.processing import _release_claimed_tasks

        self.assertEqual(_release_claimed_tasks([(INT4_MAX + 1, 1)]), 0)

    def test_every_id_array_is_cast_to_bigint(self):
        # The claim, release, persist and extract_data-delete statements all
        # unnest (dataset_id, id) pairs; none may narrow the id.
        from analytics.tasks import processing

        source = inspect.getsource(processing)
        self.assertNotIn("%s::int[], %s::int[]", source)
        self.assertEqual(source.count("%s::int[], %s::bigint[]"), 4)
