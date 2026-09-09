from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase

from analytics.models import ExtractData, ExtractTask, ProcessingOption
from analytics.tasks import processing
from analytics.tasks.processing import _run_extract_task
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
    only its own position(s) NULL, and a rerun only touches positions that
    are still NULL.
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
        self.assertEqual(row.data_column, "float")
        self.assertEqual(row.float_values, [1.5])
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
        self.assertEqual(count_row.data_column, "int")
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

    # --- rerun only touches NULL positions ------------------------------------

    def test_rerun_only_reprocesses_null_positions(self):
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

        # Only the previously-NULL position (r1) should have been recomputed;
        # r0 and r2 were already filled and must not have been called again.
        self.assertEqual(call_log, ["r1"])

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
        self.assertEqual(call_log, ["r1"])
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
