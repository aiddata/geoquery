import hashlib
import json
from unittest import mock

from django.contrib.gis.geos import Point
from django.db import OperationalError, connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from analytics.models import ExtractData, ExtractTask, ProcessingOption
from analytics.tasks import processing
from analytics.tasks.processing import _load_claimed_task, _run_extract_task
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

    def make_task(self, resources, *, status=LOCKED, kwargs=None):
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
        task = self.make_task(resources, status=LOCKED)

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
        task = self.make_task(resources, status=LOCKED)

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
        task = self.make_task(resources, status=LOCKED)
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
        task = self.make_task(resources, status=LOCKED)

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
        task = self.make_task(resources, status=LOCKED)

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
        task = self.make_task([r2, r0, r1], status=LOCKED)

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
        task = self.make_task(resources, status=LOCKED)
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

        # Simulate a retry: claim the task again, and this time every
        # resource succeeds.
        ExtractTask.objects.filter(id=task.id).update(status=LOCKED)
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
        task = self.make_task(resources, status=LOCKED)

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

        # Simulate a retry: claim the task again, and this time every
        # resource succeeds -- "mean" is still the only name, but it now
        # exists in both existing_by_name (from the first run) and produced
        # (this run recomputes the previously-NULL position).
        ExtractTask.objects.filter(id=task.id).update(status=LOCKED)
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
        task = self.make_task(resources, status=LOCKED)

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

    def test_inactive_dataset_task_is_not_run(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=LOCKED)
        self.dataset.active = False
        self.dataset.save(update_fields=["active"])

        result = _run_extract_task(task.id)

        self.assertIsNone(result)
        task.refresh_from_db()
        self.assertEqual(task.status, LOCKED)

    def test_null_position_does_not_block_completion(self):
        # A run that raises nothing is complete, even where a processor
        # produced no value for a position. This is the precondition for
        # storing nodata as a real NULL: the completion check no longer
        # scans stored arrays. (The nodata value itself is still the string
        # 'None' until _classify_value changes in a later commit.)
        resources = self.make_resources(3)
        task = self.make_task(resources, status=LOCKED)

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
        task = self.make_task(resources, status=LOCKED)

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
        task = self.make_task(resources, status=LOCKED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", 1.5)]
        ):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_value, 1.5)
        self.assertIsNone(row.float_values)

    def test_grouped_task_writes_array_not_scalar(self):
        resources = self.make_resources(3)
        task = self.make_task(resources, status=LOCKED)

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
        task = self.make_task(resources, status=LOCKED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", 4.5)]
        ):
            _run_extract_task(task.id)
        self.assertEqual(self.data_row(task, "mean").float_value, 4.5)

        ExtractTask.objects.filter(id=task.id).update(status=LOCKED)

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
        task = self.make_task(resources, status=LOCKED)

        def func(geometry, path, **kw):
            if path.stem == "r0":
                return [("mean", None)]
            return [("mean", float(int(path.stem[-1])))]

        with mock.patch.object(processing, "get_func", return_value=func):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [None, 1.0, 2.0])
        self.assertIsNone(row.str_values)

    # --- the lookup prunes to one partition and fetches only what it reads --

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
        # The lookup needs the explicit partition filter, as does the final
        # status update. No deferred-field reads are needed.
        resources = self.make_resources(1)
        task = self.make_task(resources)

        queries = self.run_capturing_queries(task, task.dataset_id)

        touching = [
            q for q in queries
            if "extract_tasks" in q
        ]
        self.assertEqual(len(touching), 3, touching)  # lookup, recheck claim, complete
        lookup, recheck, complete = touching
        self.assertIn(f"t.dataset_id = {task.dataset_id}", lookup)
        for query in (recheck, complete):
            self.assertIn(f'"dataset_id" = {task.dataset_id}', query)
            self.assertIn(f'"id" IN ({task.id})', query)
        task.refresh_from_db()
        self.assertEqual(task.status, DONE)

    def test_the_lookup_only_reads(self):
        # The claim already moved the row to running; a second write to
        # extract_tasks per task is exactly what the lookup replaced.
        task = self.make_task(self.make_resources(1))

        queries = self.run_capturing_queries(task, task.dataset_id)

        lookup = next(q for q in queries if "FROM extract_tasks AS t" in q)
        self.assertTrue(lookup.lstrip().startswith("SELECT"), lookup)
        self.assertNotIn("FOR UPDATE", lookup)

    def test_claim_and_completion_times_both_come_from_the_database_clock(self):
        # A worker's clock can be skewed against the primary's, and a
        # duration taken across the two can even come out negative.
        task = self.make_task(self.make_resources(1), status=PENDING)
        [(task_id, dataset_id)] = processing.claim_pending_tasks(1)

        queries = self.run_capturing_queries(task, dataset_id)

        complete = next(q for q in queries if "complete_time" in q)
        self.assertIn('"complete_time" = STATEMENT_TIMESTAMP()', complete)
        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertLessEqual(task.update_time, task.complete_time)

    def test_lookup_does_not_fetch_columns_it_never_reads(self):
        resources = self.make_resources(1)
        task = self.make_task(resources)

        queries = self.run_capturing_queries(task, task.dataset_id)

        [lookup] = [q for q in queries if "FROM extract_tasks AS t" in q]
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
        task = self.make_task(resources)

        self.assertIsNone(_run_extract_task(task.id, task.dataset_id + 1))
        task.refresh_from_db()
        self.assertEqual(task.status, LOCKED)

    def test_lookup_finds_only_running_tasks_with_active_inputs(self):
        resources = self.make_resources(1)
        task = self.make_task(resources)
        tasks = ExtractTask.objects.filter(dataset_id=task.dataset_id, id=task.id)

        for status in (PENDING, QUEUED, LOCKED, DONE, FAILED):
            with self.subTest(status=status):
                tasks.update(status=status, update_time=None)
                loaded = _load_claimed_task(task.id, task.dataset_id)
                if status == LOCKED:
                    self.assertIsNotNone(loaded)
                else:
                    self.assertIsNone(loaded)
                # Reading never changes the row.
                task.refresh_from_db()
                self.assertEqual(task.status, status)
                self.assertIsNone(task.update_time)

        tasks.update(status=LOCKED)
        for related in (self.dataset, self.po, self.fm.fc):
            with self.subTest(inactive=type(related).__name__):
                related.active = False
                related.save(update_fields=["active"])
                self.assertIsNone(_load_claimed_task(task.id, task.dataset_id))
                related.active = True
                related.save(update_fields=["active"])

        self.assertIsNone(_load_claimed_task(-1, task.dataset_id))

    def test_lookup_delivers_geometry_and_both_kwargs_to_processor(self):
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

    def create_test_partitions(self):
        # Real partitions catch a statement that joins on dataset_id but still
        # plans/scans every partition. DDL and analyzed writes roll back with
        # this TestCase, leaving the shared test schema unchanged.
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

    def explain_partitions(self, sql, *, analyze=True):
        """Return scanned partitions, or all planned scans when analyze=False."""
        with connection.cursor() as cursor:
            # EXPLAIN accepts the statement, not a SET LOCAL prefix.
            sql = sql.removeprefix(processing._ASYNC_COMMIT)
            options = "ANALYZE, BUFFERS, FORMAT JSON" if analyze else "FORMAT JSON"
            cursor.execute(f"EXPLAIN ({options}) " + sql)
            plan = cursor.fetchone()[0][0]["Plan"]

        def nodes(node):
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        return [
            node["Relation Name"] for node in nodes(plan)
            if node.get("Relation Name", "").startswith("extract_tasks_")
            and node["Node Type"] != "ModifyTable"
            and (not analyze or node.get("Actual Loops", 0) > 0)
        ], plan

    def test_lookup_plan_prunes_to_one_partition(self):
        self.create_test_partitions()
        task = self.make_task(self.make_resources(1))
        with CaptureQueriesContext(connection) as queries:
            _load_claimed_task(task.id, task.dataset_id)
        [lookup] = queries.captured_queries

        scanned, plan = self.explain_partitions(lookup["sql"])
        self.assertEqual(scanned, ["extract_tasks_claim_test"], plan)

    def test_buffered_persistence_rolls_back_results_and_status_together(self):
        task = self.make_task(self.make_resources(1))
        ExtractData.objects.create(
            dataset_id=task.dataset_id, extract_task_id=task.id,
            name="old", float_value=9.0,
        )
        outcomes = []
        with mock.patch.object(processing, "get_func", return_value=lambda *a, **kw: [("mean", 1.0)]):
            _run_extract_task(task.id, task.dataset_id, outcomes=outcomes)

        def fail_after_update(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.startswith('UPDATE "extract_tasks"'):
                raise OperationalError("commit failed")
            return result

        with connection.execute_wrapper(fail_after_update), self.assertRaises(OperationalError):
            processing._persist_outcomes(outcomes)
        task.refresh_from_db()
        self.assertEqual(task.status, LOCKED)
        self.assertEqual(list(ExtractData.objects.filter(
            dataset_id=task.dataset_id, extract_task_id=task.id,
        ).values_list("name", "float_value")), [("old", 9.0)])

        # Retrying uses the same computed rows and atomically replaces them.
        processing._persist_outcomes(outcomes)
        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertEqual(list(ExtractData.objects.filter(
            dataset_id=task.dataset_id, extract_task_id=task.id,
        ).values_list("name", "float_value")), [("mean", 1.0)])

    def test_batch_persistence_plans_prune_both_partitioned_tables(self):
        self.create_test_partitions()
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE extract_data_flush_test PARTITION OF extract_data FOR VALUES IN (%s)",
                [self.dataset.id],
            )
            cursor.execute(
                "CREATE TABLE extract_data_flush_other PARTITION OF extract_data FOR VALUES IN (-2147483648)"
            )
        resources = self.make_resources(1)
        tasks = [self.make_task(resources, kwargs={"n": i}) for i in range(32)]
        outcomes = []
        with mock.patch.object(processing, "get_func", return_value=lambda *a, **kw: [("mean", 1.0)]):
            for task in tasks:
                _run_extract_task(task.id, task.dataset_id, outcomes=outcomes)
        with CaptureQueriesContext(connection) as queries:
            processing._persist_outcomes(outcomes)
        statements = [q["sql"] for q in queries if q["sql"].startswith(("SELECT", "DELETE", "UPDATE"))]
        self.assertEqual(len(statements), 3, statements)
        for sql in statements:
            with connection.cursor() as cursor:
                cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
                plan = cursor.fetchone()[0][0]["Plan"]
            serialized = json.dumps(plan)
            self.assertNotIn("extract_tasks_claim_other", serialized)
            self.assertNotIn("extract_data_flush_other", serialized)
            self.assertNotIn("extract_tasks_default", serialized)
            self.assertNotIn("extract_data_default", serialized)

    def test_persistence_groups_multiple_datasets_and_distinct_errors(self):
        resources = self.make_resources(1)
        good = self.make_task(resources, kwargs={"n": 1})
        bad = self.make_task(resources, kwargs={"n": 2})
        other = Dataset.objects.create(name="other", path="/data/other", active=True)
        resource = DatasetResource.objects.create(dataset=other, name="other", path="r.tif")
        po = ProcessingOption.objects.create(
            dataset=other, short_name="other", function="rasterstats_default_mean", active=True,
        )
        other_good = ExtractTask.objects.create(
            dataset_id=other.id, resource_ids=[resource.id], fm=self.fm, po=po, status=LOCKED,
        )
        other_bad = ExtractTask.objects.create(
            dataset_id=other.id, resource_ids=[resource.id], fm=self.fm, po=po,
            status=LOCKED, kwargs={"n": 2},
        )
        outcomes = []
        with mock.patch.object(processing, "get_func", return_value=lambda *a, **kw: [("mean", 2.0)]):
            for task in (good, other_good):
                _run_extract_task(task.id, task.dataset_id, outcomes=outcomes)
        for task, error in ((bad, "first"), (other_bad, "second")):
            with mock.patch.object(processing, "get_func", side_effect=ValueError(error)), self.assertRaises(ValueError):
                _run_extract_task(task.id, task.dataset_id, outcomes=outcomes)
        processing._flush_outcomes(outcomes)
        for task in (good, other_good):
            task.refresh_from_db()
            self.assertEqual(task.status, DONE)
        for task, error in ((bad, "first"), (other_bad, "second")):
            task.refresh_from_db()
            self.assertEqual(task.status, FAILED)
            self.assertIn(error, task.error)
        self.assertEqual(ExtractData.objects.filter(dataset_id=self.dataset.id).count(), 1)
        self.assertEqual(ExtractData.objects.filter(dataset_id=other.id).count(), 1)

    def test_batch_claim_and_release_exclude_unrelated_partitions_during_planning(self):
        # A single-row test can pass through execution-time pruning alone.
        # Use 64 references across two populated partitions and another
        # populated partition that must be absent from the UPDATE plans.
        datasets = [self.dataset] + [
            Dataset.objects.create(name=name, path=f"/data/{name}", active=True)
            for name in ("batch-other", "batch-unrelated")
        ]
        partition_names = [f"extract_tasks_batch_test_{i}" for i in range(3)]
        expected_refs = set()
        for i, dataset in enumerate(datasets):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE TABLE {partition_names[i]} PARTITION OF extract_tasks "
                    "FOR VALUES IN (%s)",
                    [dataset.id],
                )
            resource = DatasetResource.objects.create(
                dataset=dataset, name=f"batch-r{i}", path="r.tif"
            )
            po = ProcessingOption.objects.create(
                dataset=dataset, short_name="batch-mean",
                function="rasterstats_default_mean", active=True,
            )
            tasks = ExtractTask.objects.bulk_create([
                ExtractTask(
                    dataset_id=dataset.id, resource_ids=[resource.id],
                    fm=self.fm, po=po, status=PENDING,
                    priority=1 if i < 2 else 0, kwargs={"n": n},
                )
                for n in range(32)
            ])
            if i < 2:
                expected_refs.update((task.id, dataset.id) for task in tasks)

        with CaptureQueriesContext(connection) as queries:
            claimed = processing.claim_pending_tasks(64)
        self.assertEqual(set(claimed), expected_refs)
        [claim_update] = [q["sql"] for q in queries.captured_queries if "unnest" in q["sql"]]
        targets = ExtractTask.objects.filter(dataset_id__in=[d.id for d in datasets[:2]])
        self.assertEqual(set(targets.values_list("status", flat=True)), {LOCKED})

        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(processing._release_claimed_tasks(claimed), 64)
        [release_update] = [q["sql"] for q in queries.captured_queries if "unnest" in q["sql"]]
        self.assertEqual(set(targets.values_list("status", flat=True)), {PENDING})
        self.assertEqual(
            set(ExtractTask.objects.filter(dataset_id=datasets[2].id).values_list("status", flat=True)),
            {PENDING},
        )

        for operation, update in (("claim", claim_update), ("release", release_update)):
            with self.subTest(operation=operation):
                planned, plan = self.explain_partitions(update, analyze=False)
                self.assertEqual(set(planned), set(partition_names[:2]), plan)


class _CommittedTaskFixture(TransactionTestCase):
    """One claimed (running) task, outside TestCase's wrapping transaction,
    so autocommit and SET LOCAL behave as they do in a worker.
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
            status=LOCKED,
        )


class ProcessingCommitModeTest(_CommittedTaskFixture):
    """Every processing commit skips fsync, and the setting goes no further.

    Async commit is what keeps fsync latency on the database volume out of
    each task's critical path -- see EXTRACT_TASK_SYNCHRONOUS_COMMIT. A
    TransactionTestCase so autocommit is real: inside TestCase's wrapping
    transaction a SET LOCAL would last for the rest of the test, hiding
    exactly the leak these check for.
    """

    def run_capturing_queries(self):
        with (
            mock.patch.object(
                processing, "get_func", return_value=lambda g, p, **kw: [("mean", 1.0)]
            ),
            CaptureQueriesContext(connection) as ctx,
        ):
            _run_extract_task(self.task.id, self.task.dataset_id)
        return [q["sql"] for q in ctx.captured_queries]

    def session_setting(self):
        with connection.cursor() as cursor:
            cursor.execute("SHOW synchronous_commit")
            return cursor.fetchone()[0]

    def test_results_and_completion_commit_asynchronously(self):
        queries = self.run_capturing_queries()

        # Results and completion now share one transaction and SET LOCAL.
        self.assertEqual(queries.count("BEGIN"), 1, queries)
        self.assertEqual(queries.count("COMMIT"), 1, queries)
        self.assertEqual(queries.count(processing._ASYNC_COMMIT), 1, queries)
        insert = next(i for i, q in enumerate(queries) if 'INSERT INTO "extract_data"' in q)
        self.assertIn(processing._ASYNC_COMMIT, queries[:insert])
        # The lookup's row reached Python and the task finished.
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, DONE)
        self.assertEqual(
            ExtractData.objects.get(extract_task_id=self.task.id).float_value, 1.0
        )

    def test_the_setting_does_not_outlive_its_transaction(self):
        # SET LOCAL, not SET: on a pooled server connection a session-level
        # setting would make whatever workload reuses it non-durable.
        self.run_capturing_queries()
        self.assertEqual(self.session_setting(), "on")

    def test_prefixed_statement_runs_under_the_setting_and_keeps_its_result(self):
        with connection.cursor() as cursor:
            processing._execute_async(
                cursor, "SELECT current_setting('synchronous_commit'), %s", [7]
            )
            self.assertEqual(cursor.fetchone(), ("off", 7))
        self.assertEqual(self.session_setting(), "on")

    def test_the_batch_claim_commits_asynchronously(self):
        # It holds the fleet-wide claim lock through its commit, so an fsync
        # there would stall every claimer behind it.
        ExtractTask.objects.filter(
            dataset_id=self.task.dataset_id, id=self.task.id
        ).update(status=PENDING)

        with CaptureQueriesContext(connection) as ctx:
            claimed = processing.claim_pending_tasks(1)

        self.assertEqual(claimed, [(self.task.id, self.task.dataset_id)])
        lock = next(
            q["sql"] for q in ctx.captured_queries if "pg_advisory_xact_lock" in q["sql"]
        )
        self.assertTrue(lock.startswith(processing._ASYNC_COMMIT), lock)
        self.assertEqual(self.session_setting(), "on")

    def test_releasing_tasks_commits_asynchronously(self):
        with CaptureQueriesContext(connection) as ctx:
            released = processing._release_claimed_tasks(
                [(self.task.id, self.task.dataset_id)]
            )

        self.assertEqual(released, 1)
        [release] = [q["sql"] for q in ctx.captured_queries]
        self.assertTrue(release.startswith(processing._ASYNC_COMMIT), release)
        self.assertEqual(self.session_setting(), "on")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, PENDING)

    def test_synchronous_commit_can_be_restored_without_a_deploy(self):
        with self.settings(EXTRACT_TASK_SYNCHRONOUS_COMMIT=True):
            queries = self.run_capturing_queries()

        self.assertFalse(any("synchronous_commit" in q for q in queries), queries)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, DONE)
