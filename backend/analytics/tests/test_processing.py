import hashlib
import json
import threading
from unittest import mock

from django.contrib.gis.geos import Point
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from analytics.models import ExtractData, ExtractTask, ProcessingOption
from analytics.tasks import processing
from analytics.tasks.processing import _claim_extract_task, _run_extract_task
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection

PENDING, DONE, LOCKED, QUEUED, FAILED = 0, 1, 2, 3, -1


class _DistinctiveProcessorError(Exception):
    """A processor failure type distinct from RuntimeError.

    Used to prove that _run_extract_task re-raises the *original* caught
    exception on total failure rather than always synthesizing a fresh
    RuntimeError -- a synthesized RuntimeError would be indistinguishable
    from a preserved one if every test injected RuntimeError as the failure.
    """


class ProcessingTestCase(TestCase):
    """_run_extract_task: per-resource processing and position-aligned storage.

    Real contention isn't exercised here (see test_dispatch.py's docstring) --
    these cover the single-worker contract: resource_ids[i] maps to index i
    in every ExtractData row's value arrays, one resource's failure leaves
    only its own position(s) NULL, and a rerun recomputes every position.
    """

    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        cls.po = ProcessingOption.objects.create(
            dataset=cls.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        cls.fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))

    def make_resources(self, n):
        return [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"ds-r{i}", path=f"r{i}.tif"
            )
            for i in range(n)
        ]

    def make_task(self, resources, *, status=PENDING, kwargs=None):
        return ExtractTask.objects.create(
            resource_ids=[r.id for r in resources],
            dataset_id=self.dataset.id,
            fm=self.fm,
            po=self.po,
            status=status,
            kwargs=kwargs,
        )

    def data_row(self, task, name):
        return ExtractData.objects.get(extract_task_id=task.id, name=name)

    # --- standard 1-element task -------------------------------------------

    def test_standard_task_single_resource_success(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", 1.5)]
        ):
            result = _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertIsNotNone(task.complete_time)
        self.assertEqual(result, {"task_id": task.id, "results": 1})

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_value, 1.5)
        self.assertEqual(row.dataset_id, self.dataset.id)

    # --- grouped multi-element task, all succeed ----------------------------

    def test_grouped_task_all_resources_success_is_position_aligned(self):
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)

        def func(geometry, path, **kw):
            # value depends on which resource file this call is for, so we
            # can assert position-alignment below.
            idx = int(path.stem[-1])
            return [("mean", float(idx) * 10), ("count", idx)]

        with mock.patch.object(processing, "get_func", return_value=func):
            result = _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertEqual(result, {"task_id": task.id, "results": 2})

        mean_row = self.data_row(task, "mean")
        self.assertEqual(mean_row.float_values, [0.0, 10.0, 20.0])
        count_row = self.data_row(task, "count")
        self.assertEqual(count_row.int_values, [0, 1, 2])

    # --- grouped task, partial failure ---------------------------------------

    def test_grouped_task_partial_failure_leaves_null_without_raising(self):
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)
        failing_id = resources[1].id

        def func(geometry, path, **kw):
            if path.stem == "r1":
                raise RuntimeError("boom")
            idx = int(path.stem[-1])
            return [("mean", float(idx))]

        with mock.patch.object(processing, "get_func", return_value=func):
            # Must not raise: at least one position succeeded this run.
            result = _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, FAILED)
        self.assertIn(str(failing_id), task.error)
        self.assertIsNotNone(result)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [0.0, None, 2.0])

    def test_single_resource_total_failure_raises_and_marks_failed(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        def broken(geometry, path, **kw):
            raise _DistinctiveProcessorError("boom")

        with mock.patch.object(processing, "get_func", return_value=broken):
            with self.assertRaises(_DistinctiveProcessorError) as cm:
                _run_extract_task(task.id)

        # The exact original exception -- type and message -- must propagate,
        # not a synthesized RuntimeError wrapper.
        self.assertEqual(type(cm.exception), _DistinctiveProcessorError)
        self.assertEqual(cm.exception.args, ("boom",))

        task.refresh_from_db()
        self.assertEqual(task.status, FAILED)
        self.assertIn("boom", task.error)
        self.assertEqual(ExtractData.objects.filter(extract_task_id=task.id).count(), 0)

    def test_grouped_task_all_resources_fail_raises_chained_runtime_error(self):
        resources = self.make_resources(2)
        task = self.make_task(resources, status=QUEUED)

        def broken(geometry, path, **kw):
            raise ValueError(f"boom-{path.stem}")

        with mock.patch.object(processing, "get_func", return_value=broken):
            with self.assertRaises(RuntimeError) as cm:
                _run_extract_task(task.id)

        # More than one position failed this run, so there's no single
        # original exception to reproduce -- a summary RuntimeError is
        # synthesized instead, but it must chain the last original exception
        # as its cause rather than discarding it.
        self.assertIsInstance(cm.exception.__cause__, ValueError)

        task.refresh_from_db()
        self.assertEqual(task.status, FAILED)
        self.assertEqual(ExtractData.objects.filter(extract_task_id=task.id).count(), 0)

    def test_resource_ids_order_drives_position_alignment_not_db_order(self):
        # resources are created in ascending DB id order (r0, r1, r2), but
        # resource_ids below deliberately uses a different order -- this
        # proves position alignment follows task.resource_ids, not the id__in
        # query's (arbitrary) DB order. A regression that drops the by_id
        # reindex and iterates the queryset directly would put r0's value at
        # position 0 instead of r2's, failing this test.
        r0, r1, r2 = self.make_resources(3)
        task = self.make_task([r2, r0, r1], status=QUEUED)

        call_log = []

        def func(geometry, path, **kw):
            call_log.append(path.stem)
            idx = int(path.stem[-1])
            return [("mean", float(idx) * 10)]

        with mock.patch.object(processing, "get_func", return_value=func):
            result = _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertIsNotNone(result)

        row = self.data_row(task, "mean")
        # position 0 -> r2 (20.0), position 1 -> r0 (0.0), position 2 -> r1 (10.0)
        self.assertEqual(row.float_values, [20.0, 0.0, 10.0])
        self.assertEqual(call_log, ["r2", "r0", "r1"])

    # --- rerun recomputes every position -------------------------------------

    def test_rerun_recomputes_every_position(self):
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)
        failing_id = resources[1].id

        call_log = []

        def flaky(geometry, path, **kw):
            call_log.append(path.stem)
            if path.stem == "r1":
                raise RuntimeError("boom")
            idx = int(path.stem[-1])
            return [("mean", float(idx))]

        with mock.patch.object(processing, "get_func", return_value=flaky):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [0.0, None, 2.0])
        self.assertEqual(sorted(call_log), ["r0", "r1", "r2"])

        # Simulate a retry: reset status to claimable, and this time every
        # resource succeeds.
        ExtractTask.objects.filter(id=task.id).update(status=PENDING)
        call_log.clear()

        def all_succeed(geometry, path, **kw):
            call_log.append(path.stem)
            idx = int(path.stem[-1])
            return [("mean", float(idx))]

        with mock.patch.object(processing, "get_func", return_value=all_succeed):
            result = _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertIsNotNone(result)

        # Every position is recomputed on a retry -- a NULL no longer means
        # "position i still needs work" (it will shortly mean "nodata"), so
        # there is nothing left to derive a skip list from.
        self.assertEqual(call_log, ["r0", "r1", "r2"])

        row.refresh_from_db()
        self.assertEqual(row.float_values, [0.0, 1.0, 2.0])

    def test_rerun_results_count_is_not_inflated_by_overlapping_name(self):
        # Rerunning a task that fills a previously-NULL position for a name
        # that already has other positions filled from an earlier run must
        # report `results` as the number of distinct names, not
        # len(existing_by_name) + len(produced) -- the latter double-counts
        # "mean" here since it appears in both dicts.
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)

        call_log = []

        def flaky(geometry, path, **kw):
            call_log.append(path.stem)
            if path.stem == "r1":
                raise RuntimeError("boom")
            idx = int(path.stem[-1])
            return [("mean", float(idx))]

        with mock.patch.object(processing, "get_func", return_value=flaky):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [0.0, None, 2.0])

        # Simulate a retry: reset status to claimable, and this time every
        # resource succeeds -- "mean" is still the only name, but it now
        # exists in both existing_by_name (from the first run) and produced
        # (this run recomputes the previously-NULL position).
        ExtractTask.objects.filter(id=task.id).update(status=PENDING)
        call_log.clear()

        def all_succeed(geometry, path, **kw):
            call_log.append(path.stem)
            idx = int(path.stem[-1])
            return [("mean", float(idx))]

        with mock.patch.object(processing, "get_func", return_value=all_succeed):
            result = _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertEqual(call_log, ["r0", "r1", "r2"])
        # One distinct name ("mean"), not existing_by_name(1) + produced(1) = 2.
        self.assertEqual(result, {"task_id": task.id, "results": 1})

    # --- empty result list is a legitimate success, not a failure -----------

    def test_empty_result_list_counts_as_successful_position(self):
        # A processor call that returns [] (no named results at all) is a
        # legitimate, successful outcome for that position -- it must not be
        # left retriable/NULL or treated as a failure, even though it
        # contributes no ExtractData rows.
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: []
        ):
            result = _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertIsNotNone(task.complete_time)
        self.assertEqual(result, {"task_id": task.id, "results": 0})
        self.assertEqual(ExtractData.objects.filter(extract_task_id=task.id).count(), 0)

    # --- claim filtering (dataset_id__in replaces resource__dataset__active) --

    def test_inactive_dataset_task_is_not_claimed(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)
        self.dataset.active = False
        self.dataset.save(update_fields=["active"])

        result = _run_extract_task(task.id)

        self.assertIsNone(result)
        task.refresh_from_db()
        self.assertEqual(task.status, QUEUED)

    def test_null_position_does_not_block_completion(self):
        # A run that raises nothing is complete, even where a processor
        # produced no value for a position. This is the precondition for
        # storing nodata as a real NULL: the completion check no longer
        # scans stored arrays. (The nodata value itself is still the string
        # 'None' until _classify_value changes in a later commit.)
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)

        def sparse(geometry, path, **kw):
            if path.stem == "r1":
                return []  # legitimate success that yields no named result
            idx = int(path.stem[-1])
            return [("mean", float(idx))]

        with mock.patch.object(processing, "get_func", return_value=sparse):
            _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertIsNone(task.error)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [0.0, None, 2.0])
        self.assertEqual(
            ExtractData.objects.filter(extract_task_id=task.id).count(), 1
        )

    # --- nodata is NULL, not the string "None" -----------------------------

    def test_nodata_is_stored_as_null_not_the_string_none(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", None)]
        ):
            _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)

        row = self.data_row(task, "mean")
        self.assertIsNone(row.float_value)
        self.assertIsNone(row.int_value)
        self.assertIsNone(row.str_value)
        self.assertIsNone(row.float_values)
        self.assertIsNone(row.int_values)
        self.assertIsNone(row.str_values)

    def test_single_resource_task_writes_scalar_not_array(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", 1.5)]
        ):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_value, 1.5)
        self.assertIsNone(row.float_values)

    def test_grouped_task_writes_array_not_scalar(self):
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)

        def func(geometry, path, **kw):
            return [("mean", float(int(path.stem[-1])) * 10)]

        with mock.patch.object(processing, "get_func", return_value=func):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [0.0, 10.0, 20.0])
        self.assertIsNone(row.float_value)

    def test_total_failure_does_not_wipe_a_previous_runs_results(self):
        # The row set is replaced wholesale on each run, which would destroy
        # good data if a retry happened to fail on every position. A run that
        # produced nothing must leave the previous run's rows alone.
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", 4.5)]
        ):
            _run_extract_task(task.id)
        self.assertEqual(self.data_row(task, "mean").float_value, 4.5)

        ExtractTask.objects.filter(id=task.id).update(status=PENDING)

        def always_fails(geometry, path, **kw):
            raise RuntimeError("boom")

        with mock.patch.object(processing, "get_func", return_value=always_fails):
            with self.assertRaises(RuntimeError):
                _run_extract_task(task.id)

        # Still there -- a transient failure must not cost us the good value.
        self.assertEqual(self.data_row(task, "mean").float_value, 4.5)

    def test_leading_nodata_does_not_type_the_row_as_str(self):
        # The bug this fixes: the row's type was taken from the FIRST value
        # seen, so a nodata at position 0 typed the whole row 'str' and
        # stringified every real value after it. Masked until now only
        # because every production array happens to have one element.
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)

        def func(geometry, path, **kw):
            if path.stem == "r0":
                return [("mean", None)]
            return [("mean", float(int(path.stem[-1])))]

        with mock.patch.object(processing, "get_func", return_value=func):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [None, 1.0, 2.0])
        self.assertIsNone(row.str_values)

    # --- the claim prunes to one partition and fetches only what it reads ---

    def run_capturing_queries(self, task, dataset_id):
        with (
            mock.patch.object(
                processing, "get_func", return_value=lambda g, p, **kw: [("mean", 1.0)]
            ),
            CaptureQueriesContext(connection) as ctx,
        ):
            _run_extract_task(task.id, dataset_id)
        return [q["sql"] for q in ctx.captured_queries]

    def test_every_extract_tasks_query_names_the_partition(self):
        # Both sides of the claim need the explicit partition filter, as
        # does the final status update. No deferred-field reads are needed.
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        queries = self.run_capturing_queries(task, task.dataset_id)

        touching = [
            q for q in queries
            if "extract_tasks" in q
        ]
        self.assertEqual(len(touching), 2, touching)  # claim, complete
        claim, complete = touching
        self.assertEqual(claim.count(f"t.dataset_id = {task.dataset_id}"), 2)
        self.assertIn(f'"extract_tasks"."dataset_id" = {task.dataset_id}', complete)
        task.refresh_from_db()
        self.assertEqual(task.status, DONE)

    def test_start_and_completion_times_both_come_from_the_database_clock(self):
        # A worker's clock can be skewed against the primary's, and a
        # duration taken across the two can even come out negative.
        task = self.make_task(self.make_resources(1), status=QUEUED)

        queries = self.run_capturing_queries(task, task.dataset_id)

        claim, complete = [q for q in queries if "extract_tasks" in q]
        self.assertIn("update_time = statement_timestamp()", claim)
        self.assertIn('"complete_time" = STATEMENT_TIMESTAMP()', complete)
        task.refresh_from_db()
        self.assertLessEqual(task.update_time, task.complete_time)

    def test_lookup_does_not_fetch_columns_it_never_reads(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        queries = self.run_capturing_queries(task, task.dataset_id)

        [lookup] = [q for q in queries if "FOR UPDATE" in q]
        for unused in (
            "spatial_extent",
            "upload_metadata",
            "attr",
            "representative_point",
        ):
            self.assertNotIn(unused, lookup)

    def test_a_mismatched_dataset_id_finds_nothing(self):
        # The pair is the task's identity on the lookup: a wrong partition key
        # must not fall through to some other row or to an unpruned search.
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        self.assertIsNone(_run_extract_task(task.id, task.dataset_id + 1))
        task.refresh_from_db()
        self.assertEqual(task.status, QUEUED)

    def test_claim_preserves_status_and_active_filters(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)
        tasks = ExtractTask.objects.filter(dataset_id=task.dataset_id, id=task.id)

        for status in (PENDING, QUEUED, LOCKED, DONE, FAILED):
            with self.subTest(status=status):
                tasks.update(status=status, update_time=None)
                claimed = _claim_extract_task(task.id, task.dataset_id)
                task.refresh_from_db()
                if status in (PENDING, QUEUED):
                    self.assertIsNotNone(claimed)
                    self.assertEqual(task.status, LOCKED)
                    self.assertIsNotNone(task.update_time)
                else:
                    self.assertIsNone(claimed)
                    self.assertEqual(task.status, status)
                    self.assertIsNone(task.update_time)

        tasks.update(status=QUEUED, update_time=None)
        for related in (self.dataset, self.po, self.fm.fc):
            with self.subTest(inactive=type(related).__name__):
                related.active = False
                related.save(update_fields=["active"])
                self.assertIsNone(_claim_extract_task(task.id, task.dataset_id))
                task.refresh_from_db()
                self.assertEqual(task.status, QUEUED)
                self.assertIsNone(task.update_time)
                related.active = True
                related.save(update_fields=["active"])

        self.assertIsNone(_claim_extract_task(-1, task.dataset_id))

    def test_claim_delivers_geometry_and_both_kwargs_to_processor(self):
        resources = self.make_resources(1)
        self.po.kwargs = {"shared": "option", "option_only": [1, None, "é"]}
        self.po.save(update_fields=["kwargs"])
        task = self.make_task(resources, kwargs={"shared": "task", "flag": True})
        processor = mock.Mock(return_value=[("mean", 1.0)])

        with mock.patch.object(processing, "get_func", return_value=processor) as get_func:
            _run_extract_task(task.id, task.dataset_id)

        get_func.assert_called_once_with(self.po.function)
        args, kwargs = processor.call_args
        self.assertEqual(args[0].wkt, "POINT (0 0)")
        self.assertEqual(str(args[1]), "/data/ds/r0.tif")
        kwargs_hash = hashlib.md5(
            json.dumps(task.kwargs, sort_keys=True).encode()
        ).hexdigest()[:8]
        self.assertEqual(kwargs, {
            "name": f"mean_{kwargs_hash}",
            "shared": "task",
            "option_only": [1, None, "é"],
            "flag": True,
        })

    def test_claim_plan_prunes_selection_and_update(self):
        # Real partitions catch an UPDATE that joins on dataset_id but still
        # plans/scans every partition. DDL and the analyzed write roll back
        # with this TestCase, leaving the shared test schema unchanged.
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE extract_tasks_claim_test PARTITION OF extract_tasks "
                "FOR VALUES IN (%s)",
                [self.dataset.id],
            )
            cursor.execute(
                "CREATE TABLE extract_tasks_claim_other PARTITION OF extract_tasks "
                "FOR VALUES IN (-2147483648)"
            )
        task = self.make_task(self.make_resources(1), status=QUEUED)
        with CaptureQueriesContext(connection) as queries:
            _claim_extract_task(task.id, task.dataset_id)
        [claim] = queries.captured_queries
        ExtractTask.objects.filter(dataset_id=task.dataset_id, id=task.id).update(
            status=QUEUED
        )

        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + claim["sql"])
            plan = cursor.fetchone()[0][0]["Plan"]

        def nodes(node):
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        scans = [
            node for node in nodes(plan)
            if node.get("Relation Name", "").startswith("extract_tasks_")
        ]
        self.assertEqual(len(scans), 2, plan)  # candidate and update target
        self.assertEqual(
            {node["Relation Name"] for node in scans}, {"extract_tasks_claim_test"}
        )


class ExtractClaimTransactionTests(TransactionTestCase):
    """Exercise committed claims and competing connections without TestCase's
    wrapping transaction hiding round trips or holding locks for the test.
    """

    def setUp(self):
        dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        resource = DatasetResource.objects.create(
            dataset=dataset, name="r0", path="r0.tif"
        )
        po = ProcessingOption.objects.create(
            dataset=dataset, short_name="mean", function="rasterstats_default_mean",
            active=True,
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))
        self.task = ExtractTask.objects.create(
            dataset_id=dataset.id, resource_ids=[resource.id], po=po, fm=fm,
            status=QUEUED,
        )

    def test_claim_is_one_statement_and_committed_before_processing(self):
        def processor(geometry, path, **kwargs):
            self.assertTrue(connection.get_autocommit())
            observer = connection.copy()
            try:
                with observer.cursor() as cursor:
                    # A separate connection can see the claim and take the
                    # row lock immediately while extraction is running.
                    cursor.execute(
                        "SELECT status, update_time FROM extract_tasks "
                        "WHERE dataset_id = %s AND id = %s FOR UPDATE NOWAIT",
                        [self.task.dataset_id, self.task.id],
                    )
                    status, update_time = cursor.fetchone()
                self.assertEqual(status, LOCKED)
                self.assertIsNotNone(update_time)
            finally:
                observer.close()
            return [("mean", 1.0)]

        with (
            mock.patch.object(processing, "get_func", return_value=processor),
            CaptureQueriesContext(connection) as queries,
        ):
            _run_extract_task(self.task.id, self.task.dataset_id)

        statements = [q["sql"] for q in queries.captured_queries]
        claim_index = next(i for i, q in enumerate(statements) if "FOR UPDATE" in q)
        self.assertEqual(claim_index, 0, statements)
        # The very next query loads resources; there is no BEGIN, UPDATE or
        # COMMIT exchange between claiming and loading.
        self.assertIn('FROM "dataset_resources"', statements[1])

    def claim_in_thread(self, results, errors, barrier=None):
        try:
            if barrier is not None:
                barrier.wait(timeout=10)
            results.append(_claim_extract_task(self.task.id, self.task.dataset_id))
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    def test_concurrent_claims_have_exactly_one_winner(self):
        results, errors = [], []
        barrier = threading.Barrier(4)
        threads = [
            threading.Thread(target=self.claim_in_thread, args=(results, errors, barrier))
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertEqual(sum(result is not None for result in results), 1)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, LOCKED)

    def test_claim_skips_a_locked_task_without_waiting(self):
        results, errors = [], []
        thread = threading.Thread(target=self.claim_in_thread, args=(results, errors))
        try:
            with transaction.atomic():
                ExtractTask.objects.select_for_update().get(
                    dataset_id=self.task.dataset_id, id=self.task.id
                )
                thread.start()
                thread.join(timeout=2)
                finished_while_locked = not thread.is_alive()
        finally:
            if thread.ident is not None:
                thread.join(timeout=10)

        self.assertTrue(finished_while_locked, "claim waited for the task's row lock")
        self.assertEqual(errors, [])
        self.assertEqual(results, [None])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, QUEUED)
