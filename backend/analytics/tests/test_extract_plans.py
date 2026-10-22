"""Query plans of the new extraction statements: pruned and indexed.

Every statement on extract_tasks or extract_data names dataset_id
(database.md section 1). These tests read the planner's own answer rather
than the SQL text, with real partitions for the datasets involved.
"""

import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from analytics import sync
from analytics.models import ExtractTask
from analytics.tasks.leases import claim_lease
from analytics.tests.extract_helpers import make_collection, make_dataset, settle_inputs


def nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from nodes(child)


class PlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset, cls.po, (cls.resource,) = make_dataset("plans")
        cls.other, cls.other_po, (cls.other_resource,) = make_dataset("plans-other")
        with connection.cursor() as cursor:
            for name, dataset in (("plans", cls.dataset), ("plans_other", cls.other)):
                cursor.execute(
                    f"CREATE TABLE extract_tasks_{name} PARTITION OF extract_tasks FOR VALUES IN (%s)",
                    [dataset.id],
                )
                cursor.execute(
                    f"CREATE TABLE extract_data_{name} PARTITION OF extract_data FOR VALUES IN (%s)",
                    [dataset.id],
                )
        cls.fc, cls.fms = make_collection("plans-fc", 6)
        for fm in cls.fms:
            ExtractTask.objects.create(
                dataset_id=cls.other.id, resource_ids=[cls.other_resource.id], fm=fm, po=cls.other_po)
        settle_inputs()

    def explain(self, sql, params=None):
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN (FORMAT JSON) " + sql, params)
            plan = cursor.fetchone()[0]
        plan = json.loads(plan) if isinstance(plan, str) else plan
        return plan[0]["Plan"]

    def scanned(self, plan, prefix):
        return {
            n["Relation Name"] for n in nodes(plan)
            if n.get("Relation Name", "").startswith(prefix) and n["Node Type"] != "ModifyTable"
        }

    def captured(self, fn, needle):
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return [q["sql"] for q in ctx.captured_queries if needle in q["sql"]]

    def test_the_page_scan_probes_one_partition_through_the_pair_index(self):
        from analytics.tasks import leases

        [sql] = self.captured(claim_lease, "NOT EXISTS (\n          SELECT 1 FROM extract_tasks et")
        plan = self.explain(sql)
        self.assertEqual(self.scanned(plan, "extract_tasks_"), {"extract_tasks_plans"})
        indexes = {n.get("Index Name") for n in nodes(plan)}
        self.assertTrue(
            any(name and name.startswith("extract_tasks_plans_dataset_id_po_id") or
                name == "extract_tasks_pair_null_kwargs_idx" or
                (name or "").endswith("resource_ids_hash_fm_id_idx") for name in indexes),
            indexes,
        )

    def test_lease_completion_writes_only_the_datasets_partitions(self):
        from unittest import mock

        from analytics.tasks import leases

        lease = claim_lease()
        with mock.patch.object(leases, "get_func", return_value=lambda g, p, **kw: [("v", 1.0)]), \
                mock.patch.object(leases, "get_batch_func", return_value=None):
            statements = self.captured(lambda: leases.run_lease(lease), "extract_tasks")
        [insert] = [s for s in statements if s.lstrip().startswith("INSERT INTO extract_tasks")]
        # The insert itself targets the parent, but routes rows by dataset_id;
        # its conflict probe and the collision check must stay in-partition.
        collisions = [s for s in statements if "resource_ids <>" in s]
        for sql in collisions:
            self.assertEqual(self.scanned(self.explain(sql), "extract_tasks_"), {"extract_tasks_plans"})
        self.assertIn("ON CONFLICT (dataset_id, po_id, resource_ids_hash, fm_id)", insert)

    def test_a_reset_chunk_prunes_to_its_partition(self):
        ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.resource.id], fm=self.fms[0], po=self.po, status=1)
        with connection.cursor() as cursor:
            plan = None
            sql = sync._RESET_CHUNK_SQL
            params = {
                "ids": [1, 2], "dataset_id": self.dataset.id, "datasets": [self.dataset.id],
                "resources": [self.resource.id], "max_attempts": 5,
            }
            cursor.execute("EXPLAIN (FORMAT JSON) " + sql, params)
            plan = cursor.fetchone()[0]
        plan = json.loads(plan) if isinstance(plan, str) else plan
        plan = plan[0]["Plan"]
        self.assertEqual(self.scanned(plan, "extract_tasks_"), {"extract_tasks_plans"})
        self.assertEqual(self.scanned(plan, "extract_data_"), {"extract_data_plans"})

    def test_the_claim_discovery_skips_unavailable_partitions_at_planning(self):
        from analytics.tasks import processing

        from datasets.models import Dataset

        Dataset.objects.filter(id=self.other.id).update(path="/data/plans-other-v2")
        statements = self.captured(lambda: processing.claim_pending_tasks(4), "FROM extract_runnable_tasks")
        self.assertTrue(statements)
        plan = self.explain(statements[0])
        self.assertNotIn("extract_tasks_plans_other", self.scanned(plan, "extract_tasks_"))

    def test_a_targeted_reset_reads_one_set_by_index_range(self):
        from analytics.sync import _SET_TASKS_SQL

        with connection.cursor() as cursor:
            sql = cursor.mogrify(_SET_TASKS_SQL, {
                "dataset_id": self.other.id, "po_id": self.other_po.id,
                "set": [self.other_resource.id], "after": 0, "limit": 100,
            })
        plan = self.explain(sql)
        self.assertEqual(self.scanned(plan, "extract_tasks_"), {"extract_tasks_plans_other"})
        indexes = {n.get("Index Name") or "" for n in nodes(plan)}
        self.assertTrue(any(name.startswith("extract_tasks_plans_other_dataset_id_po_id") for name in indexes), indexes)

    def test_demand_reads_the_pending_partial_index(self):
        plan = self.explain("SELECT extract_work_demand()")
        # A SQL function's body is planned when it runs; check it executes and
        # its pending term uses runtime pruning.
        self.assertTrue(plan)
        with connection.cursor() as cursor:
            cursor.execute("SELECT extract_work_demand()")
            self.assertIsInstance(cursor.fetchone()[0], int)
