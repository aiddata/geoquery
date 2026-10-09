"""Task ids past int4's range: the SQL that carries them, and the converter.

extract_tasks_id_seq ran out at 2,147,483,647; see database.md section 11.
"""

from unittest.mock import patch

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


class ReplicaWaitTests(SimpleTestCase):
    """Between partitions the converter waits on the replication slots.

    Rows are (slot_name, active, wal_status, bytes_behind), as _slots returns.
    """

    GB = 2**30

    def _command(self, slot_readings):
        from io import StringIO

        from analytics.management.commands.convert_task_ids_to_bigint import Command

        cmd = Command(stdout=StringIO())
        cmd.opts = {"max_slot_lag_gb": 8.0, "lag_timeout_minutes": 1}
        readings = iter(slot_readings)
        last = {}

        def slots(_cursor):
            last["v"] = next(readings, last.get("v"))
            return last["v"]

        cmd._slots = slots
        return cmd

    def test_returns_once_every_slot_is_close(self):
        cmd = self._command([[("a", True, "reserved", 1 * self.GB), ("b", True, "reserved", 0)]])
        with patch("time.sleep") as sleep:
            cmd._wait_for_replicas(None)
        sleep.assert_not_called()

    def test_waits_for_a_lagging_slot_to_catch_up(self):
        cmd = self._command([
            [("a", True, "reserved", 40 * self.GB)],
            [("a", True, "reserved", 2 * self.GB)],
        ])
        with patch("time.sleep") as sleep:
            cmd._wait_for_replicas(None)
        self.assertEqual(sleep.call_count, 1)

    def test_an_unreserved_slot_is_waited_for_not_abandoned(self):
        # Past the limit but recoverable: nothing is written between
        # partitions, so its standby can still catch up.
        cmd = self._command([
            [("a", True, "unreserved", 120 * self.GB)],
            [("a", True, "reserved", 1 * self.GB)],
        ])
        with patch("time.sleep"):
            cmd._wait_for_replicas(None)

    def test_a_lost_slot_is_reported_and_the_rest_still_protected(self):
        cmd = self._command([
            [("a", False, "lost", None), ("b", True, "reserved", 30 * self.GB)],
            [("a", False, "lost", None), ("b", True, "reserved", 1 * self.GB)],
        ])
        with patch("time.sleep") as sleep:
            cmd._wait_for_replicas(None)
        self.assertEqual(sleep.call_count, 1)          # still waited on b
        self.assertIn("lost: ['a']", cmd.stdout._out.getvalue())

    def test_an_inactive_slot_still_counts(self):
        # A standby that is restarting still needs its unreplayed WAL.
        cmd = self._command([[("a", False, "reserved", 50 * self.GB)]])
        with patch("time.sleep"), patch("time.monotonic", side_effect=[0, 0, 120]):
            with self.assertRaises(CommandError):
                cmd._wait_for_replicas(None)
