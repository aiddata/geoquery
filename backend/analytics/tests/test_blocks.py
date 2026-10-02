import math
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
import shapely
from django.contrib.gis.geos import Polygon
from django.db import connection, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from prometheus_client import REGISTRY
from rasterio.transform import from_origin

from analytics import blocks
from analytics.blocks import Option, claim_block, compute, run_block
from analytics.management.commands.build_extract_tasks import (
    _build_extract_tasks,
    _build_global_tasks,
    sync_progress_pairs,
)
from analytics.models import ExtractData, ExtractTask, ExtractTaskBuildProgress, ProcessingOption
from analytics.processors import zonal_stats_rasterstats
from analytics.tasks.processing import _classify_value, data_values, get_func
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection

PENDING, DONE, LOCKED, QUEUED, FAILED = 0, 1, 2, 3, -1
STATS = ("min", "max", "mean", "sum", "count")


def write_raster(path, values, nodata=None):
    """A single-band EPSG:4326 GeoTIFF whose pixel (row, col) covers
    x in [col, col+1], y in [h-row-1, h-row]."""
    height, width = values.shape
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype=values.dtype, crs="EPSG:4326", nodata=nodata,
        transform=from_origin(0, height, 1, 1),
    ) as dst:
        dst.write(values, 1)
    return Path(path)


def per_task(function, geom, path, op_kwargs):
    """What the per-task path's processor call produces for one task."""
    return get_func(function)(geom, path, **op_kwargs)


def same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b and type(a) is type(b)


def blocks_counted(outcome):
    return REGISTRY.get_sample_value("geoquery_extract_blocks_total", {"outcome": outcome}) or 0.0


def ids_drawn():
    """The extract_tasks identity's last value, to count ids a write draws."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_get_serial_sequence('extract_tasks', 'id')")
        (sequence,) = cursor.fetchone()
        cursor.execute(f"SELECT last_value FROM {sequence}")
        return cursor.fetchone()[0]


def wait_for_a_blocked_backend(cursor, timeout=10):
    """Poll until another backend of this database is waiting on a lock."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cursor.execute("SELECT pg_stat_clear_snapshot()")
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE wait_event_type = 'Lock' AND pid <> pg_backend_pid() "
            "AND datname = current_database()"
        )
        if cursor.fetchone()[0]:
            return True
        time.sleep(0.05)
    return False


class ComputeParityTests(SimpleTestCase):
    """Batched compute() must reproduce the per-task processor calls exactly:
    same names, same values, same types -- the existing ~700M rows were
    written by the per-task path, and blocks must not change them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        values = np.arange(100, dtype="float32").reshape(10, 10)
        values[0, 0] = -1  # nodata
        self.float_raster = write_raster(Path(self.tmp.name) / "f.tif", values, nodata=-1)
        classes = (np.arange(100, dtype="uint8").reshape(10, 10) % 3) + 1
        self.class_raster = write_raster(Path(self.tmp.name) / "c.tif", classes)
        self.geometries = {
            1: shapely.box(0, 0, 4, 4),
            2: shapely.box(2.5, 2.5, 7.5, 9.5),
            3: shapely.Polygon([(1, 1), (9, 1), (5, 8)]),
            4: shapely.box(0, 9, 1, 10),  # the nodata pixel only
            5: shapely.box(8, 8, 14, 14),  # partly off the raster
            6: shapely.box(20, 20, 21, 21),  # entirely off it
        }

    def assert_parity(self, options, resources, geometries=None):
        geometries = geometries or self.geometries
        produced, failures = compute(geometries, resources, options)
        self.assertEqual(failures, {})
        for gid, geom in geometries.items():
            for option in options:
                expected = {}
                for position, (_rid, path) in enumerate(resources):
                    for name, value in per_task(option.function, geom, path, option.op_kwargs):
                        expected.setdefault(name, {})[position] = value
                got = produced[(gid, option.po_id)]
                self.assertEqual(set(got), set(expected), (gid, option.function))
                for name in expected:
                    for position, value in expected[name].items():
                        self.assertTrue(
                            same(got[name][position], value),
                            (gid, option.function, name, got[name][position], value),
                        )

    def test_every_stat_matches_the_single_feature_functions(self):
        options = [
            Option(i, f"rasterstats_default_{stat}", {"name": stat})
            for i, stat in enumerate(STATS)
        ]
        self.assert_parity(options, [(10, self.float_raster)])

    def test_stats_with_different_kwargs_match(self):
        options = [
            Option(1, "rasterstats_default_mean", {"name": "mean"}),
            Option(2, "rasterstats_default_mean", {"name": "mean_nd", "nodata": 5}),
            Option(3, "rasterstats_default_count", {"name": "count_nd", "nodata": 5}),
        ]
        self.assert_parity(options, [(10, self.float_raster)])

    def test_mixed_geometry_batches_preserve_percentage_coverage(self):
        # rasterstats disables percentage coverage when it encounters a
        # Point/MultiPoint. That state must not leak to later polygons.
        geometries = {
            1: shapely.Point(1.5, 1.5),
            2: shapely.box(2.2, 2.2, 4.8, 4.8),
            3: shapely.MultiPoint([(1.5, 1.5), (3.5, 3.5)]),
            4: shapely.box(5.2, 5.2, 7.8, 7.8),
        }
        for coverage in (
            {"percent_cover_weighting": True},
            {"percent_cover_selection": 0.75},
            {"percent_cover_weighting": True, "percent_cover_selection": 0.75},
        ):
            for limit in (None, 4):
                with self.subTest(coverage=coverage, limit=limit):
                    options = [
                        Option(i, f"rasterstats_default_{stat}", {
                            "name": stat, "all_touched": True,
                            "percent_cover_scale": 10, "limit": limit, **coverage,
                        })
                        for i, stat in enumerate(STATS)
                    ]
                    self.assert_parity(options, [(10, self.float_raster)], geometries)

    def test_categorical_matches_including_zero_fill(self):
        category_map = {1: "one", 2: "two", 3: "three", 4: "four"}
        options = [
            Option(1, "rasterstats_default_categorical",
                   {"name": "lc", "category_map": category_map}),
            # A mapped dataset passes the category map to every option.
            Option(2, "rasterstats_default_mean",
                   {"name": "mean", "category_map": category_map}),
        ]
        self.assert_parity(options, [(10, self.class_raster)])

    def test_grouped_resources_fill_their_own_positions(self):
        options = [Option(1, "rasterstats_default_mean", {"name": "mean"})]
        self.assert_parity(options, [(10, self.float_raster), (11, self.class_raster)])

    def test_options_are_batched_into_one_call_per_kwargs_group(self):
        options = [
            Option(i, f"rasterstats_default_{stat}", {"name": stat})
            for i, stat in enumerate(STATS)
        ]
        real = zonal_stats_rasterstats.rs.zonal_stats
        with mock.patch.object(
            zonal_stats_rasterstats.rs, "zonal_stats", side_effect=real
        ) as zonal_stats:
            compute(self.geometries, [(10, self.float_raster)], options)
        self.assertEqual(zonal_stats.call_count, 1)

    def test_one_bad_geometry_fails_only_its_own_tasks(self):
        options = [
            Option(1, "rasterstats_default_mean", {"name": "mean"}),
            Option(2, "rasterstats_default_max", {"name": "max"}),
        ]
        bad = self.geometries[3]
        real = zonal_stats_rasterstats.rs.zonal_stats

        def zonal_stats(feats, *args, **kwargs):
            if any(f.equals(bad) for f in feats):
                raise RuntimeError("bad geometry")
            return real(feats, *args, **kwargs)

        with mock.patch.object(zonal_stats_rasterstats.rs, "zonal_stats", side_effect=zonal_stats):
            produced, failures = compute(self.geometries, [(10, self.float_raster)], options)

        self.assertEqual(set(failures), {(3, 1), (3, 2)})
        self.assertEqual(failures[(3, 1)][0][:2], (10, 0))
        self.assertNotIn((3, 1), produced)
        self.assertIn((1, 1), produced)
        self.assertIn((2, 2), produced)

    def test_functions_without_a_batch_form_run_per_feature(self):
        func = mock.Mock(return_value=[("v", 1.5)])
        options = [Option(1, "landmarkmap_filter_and_agg", {"name": "v", "x": 1})]
        with mock.patch("analytics.tasks.processing.get_func", return_value=func):
            produced, failures = compute(self.geometries, [(10, self.float_raster)], options)
        self.assertEqual(func.call_count, len(self.geometries))
        func.assert_any_call(self.geometries[1], self.float_raster, name="v", x=1)
        self.assertEqual(produced[(1, 1)], {"v": {0: 1.5}})
        self.assertEqual(failures, {})

    def test_a_readable_raster_whose_every_geometry_fails_records_failures(self):
        # Not an outage: blocks recompute rows at -1, so a block can consist
        # entirely of deterministic failures. They must stay per-task ones.
        options = [Option(1, "rasterstats_default_mean", {"name": "mean"})]
        with mock.patch.object(
            zonal_stats_rasterstats.rs, "zonal_stats", side_effect=RuntimeError("bad geometry")
        ):
            produced, failures = compute(self.geometries, [(10, self.float_raster)], options)

        self.assertEqual(produced, {})
        self.assertEqual(set(failures), {(gid, 1) for gid in self.geometries})

    def test_an_unreadable_raster_raises_instead_of_failing_every_feature(self):
        options = [Option(1, "rasterstats_default_mean", {"name": "mean"})]
        garbage = Path(self.tmp.name) / "garbage.tif"
        garbage.write_bytes(b"not a raster")
        real = zonal_stats_rasterstats.rs.zonal_stats

        for path in (Path(self.tmp.name) / "missing.tif", garbage):
            with self.subTest(path=path.name), mock.patch.object(
                zonal_stats_rasterstats.rs, "zonal_stats", side_effect=real
            ) as zonal_stats:
                with self.assertRaises(blocks.ResourceUnreadable):
                    compute(self.geometries, [(10, path)], options)
                # The batched call only: no per-feature retries against a
                # file that cannot be opened.
                self.assertEqual(zonal_stats.call_count, 1)

    def test_a_missing_path_is_unreadable_for_functions_without_a_batch_form(self):
        func = mock.Mock(side_effect=RuntimeError("boom"))
        options = [Option(1, "landmarkmap_filter_and_agg", {"name": "v"})]
        with mock.patch("analytics.tasks.processing.get_func", return_value=func):
            with self.assertRaises(blocks.ResourceUnreadable):
                compute(self.geometries, [(10, Path(self.tmp.name) / "missing.gpkg")], options)
            self.assertEqual(func.call_count, 1)

            func.reset_mock()
            produced, failures = compute(self.geometries, [(10, self.float_raster)], options)
        self.assertEqual(func.call_count, len(self.geometries))
        self.assertEqual(produced, {})
        self.assertEqual(set(failures), {(gid, 1) for gid in self.geometries})

    def test_should_stop_ends_early(self):
        options = [Option(1, "rasterstats_default_mean", {"name": "mean"})]
        produced, _ = compute(
            self.geometries, [(10, self.float_raster)], options, should_stop=lambda: True
        )
        self.assertEqual(produced, {})


class BlockTestCase(TransactionTestCase):
    """End to end against the database: claim, scan, compute, write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        values = np.arange(100, dtype="float32").reshape(10, 10)
        write_raster(Path(self.tmp.name) / "r1.tif", values)
        write_raster(Path(self.tmp.name) / "r2.tif", values * 2)

        self.dataset = self.make_dataset("ds")
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif",
            temporal=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        self.po_mean = self.make_po(self.dataset, "mean")
        self.po_max = self.make_po(self.dataset, "max")

        fc = FeatureCollection.objects.create(
            name="fc", path="/data/fc", active=True, is_user_upload=False
        )
        boxes = [(0, 0, 3, 3), (2, 2, 6, 6), (5, 1, 9, 4), (1, 6, 4, 9)]
        self.fms = [
            FeatMap.objects.create(
                fc=fc, geom=Feature.objects.create(shape=Polygon.from_bbox(b))
            )
            for b in boxes
        ]
        # Rows outside the global feature set: an inactive collection and a
        # user upload. Blocks must skip them, as the builder does.
        for name, kwargs in (("off", {"active": False}), ("up", {"is_user_upload": True})):
            other = FeatureCollection.objects.create(
                name=name, path=f"/data/{name}", **{"active": True, **kwargs}
            )
            FeatMap.objects.create(
                fc=other, geom=Feature.objects.create(shape=Polygon.from_bbox((0, 0, 1, 1)))
            )

    def make_dataset(self, name, **kwargs):
        return Dataset.objects.create(
            name=name, path=self.tmp.name if name == "ds" else f"{self.tmp.name}/{name}",
            active=True, is_global=True, **kwargs,
        )

    def make_po(self, dataset, stat, **kwargs):
        return ProcessingOption.objects.create(
            dataset=dataset, short_name=stat,
            function=f"rasterstats_default_{stat}", active=True, **kwargs,
        )

    def expected(self, stat, fm, raster="r1.tif"):
        geom = shapely.from_wkb(bytes(fm.geom.shape.wkb))
        ((_, value),) = per_task(
            f"rasterstats_default_{stat}", geom, Path(self.tmp.name) / raster, {"name": stat}
        )
        return _classify_value(value)[1]

    def make_grouped(self):
        """A dataset whose two monthly resources form one yearly bucket."""
        grouped = self.make_dataset("grp", task_group_period="year")
        Path(grouped.path).mkdir()
        values = np.arange(100, dtype="float32").reshape(10, 10)
        resources = []
        for month, factor in ((1, 1), (2, 3)):
            write_raster(Path(grouped.path) / f"m{month}.tif", values * factor)
            resources.append(DatasetResource.objects.create(
                dataset=grouped, name=f"grp-{month}", path=f"m{month}.tif",
                temporal=datetime(2020, month, 1, tzinfo=timezone.utc),
            ))
        return grouped, resources, self.make_po(grouped, "mean")

    def progress(self, po):
        return ExtractTaskBuildProgress.objects.get(po=po, resource_ids=[self.resource.id])

    def run_all(self, **kwargs):
        sync_progress_pairs()
        results = []
        while (result := run_block(**kwargs)) is not None:
            results.append(result)
        return results


class BlockRunTests(BlockTestCase):
    def test_writes_complete_tasks_with_per_task_values(self):
        results = self.run_all()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["completed"], 8)
        tasks = ExtractTask.objects.filter(dataset_id=self.dataset.id)
        self.assertEqual(tasks.count(), 8)
        for task in tasks:
            self.assertEqual(task.status, DONE)
            self.assertIsNotNone(task.complete_time)
            self.assertEqual(task.resource_ids, [self.resource.id])
            self.assertEqual(task.priority, 0)
            self.assertIsNone(task.kwargs)
            (row,) = ExtractData.objects.filter(dataset_id=task.dataset_id, extract_task=task)
            self.assertEqual(row.name, task.po.short_name)
            self.assertEqual(row.float_value, self.expected(task.po.short_name, task.fm))

        max_fm = FeatMap.objects.order_by("-id").first().id
        for po in (self.po_mean, self.po_max):
            progress = self.progress(po)
            self.assertEqual(progress.computed_up_to_fm_id, max_fm)
            self.assertIsNone(progress.block_claimed_at)
            self.assertIsNone(progress.block_claim_token)

    def test_block_size_splits_the_range(self):
        results = self.run_all(block_size=3)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["hi"], self.fms[2].id)
        self.assertEqual(results[0]["completed"], 6)
        self.assertEqual(results[1]["completed"], 2)
        self.assertEqual(ExtractTask.objects.filter(dataset_id=self.dataset.id).count(), 8)

    def test_one_block_covers_every_option_of_a_resource(self):
        sync_progress_pairs()
        block = claim_block()
        self.assertEqual(
            {po_id for po_id, *_ in block.options}, {self.po_mean.id, self.po_max.id}
        )
        self.assertEqual(len(block.pair_ids), 2)

    def test_existing_rows_are_skipped_taken_over_or_left_alone(self):
        fm_done, fm_pending, fm_locked, fm_failed = self.fms

        def task(fm, status):
            return ExtractTask.objects.create(
                dataset_id=self.dataset.id, resource_ids=[self.resource.id],
                fm=fm, po=self.po_mean, status=status,
            )

        done = task(fm_done, DONE)
        ExtractData.objects.create(
            dataset_id=self.dataset.id, extract_task=done, name="mean", float_value=-7.0
        )
        pending = task(fm_pending, PENDING)
        locked = task(fm_locked, LOCKED)
        failed = task(fm_failed, FAILED)
        ExtractData.objects.create(
            dataset_id=self.dataset.id, extract_task=failed, name="stale", float_value=1.0
        )

        before = ids_drawn()
        (result,) = self.run_all()

        self.assertEqual(result["skipped"], 2)  # done and locked
        self.assertEqual(result["completed"], 6)
        # One id per row actually inserted (the four po_max tasks); taking
        # over the pending and failed rows draws none.
        self.assertEqual(ids_drawn() - before, 4)
        # Already done: not recomputed, data untouched.
        self.assertEqual(ExtractData.objects.get(extract_task=done).float_value, -7.0)
        # Pending: taken over in place, same id.
        pending.refresh_from_db()
        self.assertEqual(pending.status, DONE)
        self.assertIsNotNone(pending.complete_time)
        self.assertEqual(
            ExtractData.objects.get(extract_task=pending).float_value,
            self.expected("mean", fm_pending),
        )
        # In flight on the per-task path: left alone.
        locked.refresh_from_db()
        self.assertEqual(locked.status, LOCKED)
        self.assertFalse(ExtractData.objects.filter(extract_task=locked).exists())
        # Failed: recomputed, previous rows replaced wholesale.
        failed.refresh_from_db()
        self.assertEqual(failed.status, DONE)
        self.assertEqual(
            list(ExtractData.objects.filter(extract_task=failed).values_list("name", flat=True)),
            ["mean"],
        )
        self.assertEqual(
            ExtractTask.objects.filter(dataset_id=self.dataset.id, po=self.po_mean).count(), 4
        )

    def test_a_row_claimed_by_the_per_task_path_mid_block_keeps_its_own_result(self):
        pending = ExtractTask.objects.create(
            dataset_id=self.dataset.id, resource_ids=[self.resource.id],
            fm=self.fms[0], po=self.po_mean, status=PENDING,
        )
        real = blocks.compute

        def compute_then_claim(*args, **kwargs):
            ExtractTask.objects.filter(id=pending.id, dataset_id=self.dataset.id).update(
                status=QUEUED
            )
            return real(*args, **kwargs)

        with mock.patch.object(blocks, "compute", side_effect=compute_then_claim):
            (result,) = self.run_all()

        self.assertEqual(result["unavailable"], 1)
        self.assertEqual(result["completed"], 7)
        pending.refresh_from_db()
        self.assertEqual(pending.status, QUEUED)
        self.assertFalse(ExtractData.objects.filter(extract_task=pending).exists())

    def test_an_already_done_range_only_advances_the_watermark(self):
        self.run_all()
        ExtractTaskBuildProgress.objects.update(computed_up_to_fm_id=None)

        with mock.patch.object(blocks, "compute", return_value=({}, {})) as compute_:
            (result,) = self.run_all()

        self.assertEqual(compute_.call_args.args[0], {})  # no geometries to compute
        self.assertEqual(result["skipped"], 8)
        self.assertEqual(result["completed"], 0)
        max_fm = FeatMap.objects.order_by("-id").first().id
        self.assertEqual(self.progress(self.po_mean).computed_up_to_fm_id, max_fm)

    def test_an_already_done_range_opens_no_raster(self):
        self.run_all()
        ExtractTaskBuildProgress.objects.update(computed_up_to_fm_id=None)

        with mock.patch.object(zonal_stats_rasterstats.rs, "zonal_stats") as zonal_stats:
            (result,) = self.run_all()

        zonal_stats.assert_not_called()
        self.assertEqual(result["skipped"], 8)

    def assert_block_errors_and_writes_nothing(self):
        sync_progress_pairs()
        errors_before = blocks_counted("error")
        result = run_block()

        self.assertTrue(result.get("error"), result)
        self.assertEqual(blocks_counted("error") - errors_before, 1)
        self.assertFalse(ExtractTask.objects.exists())
        for po in (self.po_mean, self.po_max):
            progress = self.progress(po)
            self.assertIsNone(progress.computed_up_to_fm_id)
            self.assertIsNotNone(progress.block_claim_token)
        # Backed off: still leased, so the next chain moves on.
        self.assertIsNone(claim_block())

    def test_a_missing_raster_errors_the_block_instead_of_failing_its_tasks(self):
        # An outage, not bad geometries: writing every task as -1 and
        # advancing the watermark would hand the whole range to the per-task
        # path's retries.
        labels = {"dataset_id": str(self.dataset.id), "resource_id": str(self.resource.id)}
        metric = "geoquery_extract_block_resource_errors_total"
        before = REGISTRY.get_sample_value(metric, labels) or 0
        (Path(self.tmp.name) / "r1.tif").unlink()
        self.assert_block_errors_and_writes_nothing()
        self.assertEqual(REGISTRY.get_sample_value(metric, labels) - before, 1)

    def test_geometry_deleted_after_scan_is_counted_as_unavailable(self):
        real = blocks.load_inputs

        def delete_then_load(*args, **kwargs):
            self.fms[0].geom.delete()
            return real(*args, **kwargs)

        labels = {"dataset_id": str(self.dataset.id), "outcome": "unavailable"}
        before = REGISTRY.get_sample_value("geoquery_extract_tasks_total", labels) or 0
        with mock.patch.object(blocks, "load_inputs", side_effect=delete_then_load):
            (result,) = self.run_all()
        self.assertEqual(result["completed"], 6)
        self.assertEqual(result["unavailable"], 2)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(
            REGISTRY.get_sample_value("geoquery_extract_tasks_total", labels) - before, 2
        )

    def test_a_corrupt_raster_errors_the_block_instead_of_failing_its_tasks(self):
        (Path(self.tmp.name) / "r1.tif").write_bytes(b"not a raster")
        self.assert_block_errors_and_writes_nothing()

    def test_a_readable_raster_whose_every_feature_fails_is_still_written(self):
        with mock.patch.object(
            zonal_stats_rasterstats.rs, "zonal_stats", side_effect=RuntimeError("bad geometry")
        ):
            (result,) = self.run_all()

        self.assertNotIn("error", result)
        self.assertEqual(result["failed"], 8)
        self.assertEqual(
            ExtractTask.objects.filter(dataset_id=self.dataset.id, status=FAILED).count(), 8
        )
        max_fm = FeatMap.objects.order_by("-id").first().id
        self.assertEqual(self.progress(self.po_mean).computed_up_to_fm_id, max_fm)

    def test_failed_features_become_failed_tasks(self):
        bad = shapely.from_wkb(bytes(self.fms[1].geom.shape.wkb))
        real = zonal_stats_rasterstats.rs.zonal_stats

        def zonal_stats(feats, *args, **kwargs):
            if any(f.equals(bad) for f in feats):
                raise RuntimeError("bad geometry")
            return real(feats, *args, **kwargs)

        with mock.patch.object(zonal_stats_rasterstats.rs, "zonal_stats", side_effect=zonal_stats):
            (result,) = self.run_all()

        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["completed"], 6)
        failed = ExtractTask.objects.filter(dataset_id=self.dataset.id, status=FAILED)
        self.assertEqual({t.fm_id for t in failed}, {self.fms[1].id})
        for task in failed:
            self.assertIn("bad geometry", task.error)
            self.assertIsNone(task.complete_time)
            self.assertFalse(ExtractData.objects.filter(extract_task=task).exists())

    def test_grouped_dataset_stores_position_aligned_arrays(self):
        grouped, resources, po = self.make_grouped()

        with override_settings(EXTRACT_BLOCK_DATASETS=[grouped.id]):
            (result,) = self.run_all()

        self.assertEqual(result["completed"], 4)
        task = ExtractTask.objects.get(dataset_id=grouped.id, po=po, fm=self.fms[0])
        self.assertEqual(task.resource_ids, [r.id for r in resources])
        self.assertEqual(task.task_group_period, "year")
        row = ExtractData.objects.get(dataset_id=grouped.id, extract_task=task)
        self.assertEqual(row.float_values, [
            self.expected("mean", self.fms[0], "grp/m1.tif"),
            self.expected("mean", self.fms[0], "grp/m2.tif"),
        ])

    def test_the_dataset_allowlist_restricts_claims(self):
        sync_progress_pairs()
        with override_settings(EXTRACT_BLOCK_DATASETS=[self.dataset.id + 1000]):
            self.assertIsNone(claim_block())
        with override_settings(EXTRACT_BLOCK_DATASETS=[self.dataset.id]):
            self.assertIsNotNone(claim_block())

    def test_a_row_failed_after_the_scan_has_its_data_replaced(self):
        # Inserted and failed by the per-task path while the block computed,
        # so the scan never saw it. Its rows must still be replaced; keeping
        # them collides with the block's own on extract_data's primary key.
        real = blocks.compute
        made = {}

        def compute_then_fail_elsewhere(*args, **kwargs):
            made["task"] = ExtractTask.objects.create(
                dataset_id=self.dataset.id, resource_ids=[self.resource.id],
                fm=self.fms[0], po=self.po_mean, status=FAILED,
            )
            ExtractData.objects.create(
                dataset_id=self.dataset.id, extract_task=made["task"], name="mean",
                float_value=-7.0,
            )
            return real(*args, **kwargs)

        with mock.patch.object(blocks, "compute", side_effect=compute_then_fail_elsewhere):
            (result,) = self.run_all()

        self.assertEqual(result["completed"], 8)
        task = made["task"]
        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        (row,) = ExtractData.objects.filter(dataset_id=self.dataset.id, extract_task=task)
        self.assertEqual(row.float_value, self.expected("mean", self.fms[0]))

    def test_an_oversized_value_fails_only_its_task(self):
        real = blocks.compute
        geom_id = self.fms[0].geom_id

        def compute_with_a_long_value(*args, **kwargs):
            produced, failures = real(*args, **kwargs)
            produced[(geom_id, self.po_mean.id)] = {"mean": {0: "x" * 150}}
            return produced, failures

        with mock.patch.object(blocks, "compute", side_effect=compute_with_a_long_value):
            (result,) = self.run_all()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["completed"], 7)
        task = ExtractTask.objects.get(
            dataset_id=self.dataset.id, fm=self.fms[0], po=self.po_mean
        )
        self.assertEqual(task.status, FAILED)
        self.assertEqual(task.error, "value too long for extract_data.str_value")
        self.assertFalse(ExtractData.objects.filter(extract_task=task).exists())

    def run_grouped_with(self, values_by_pos):
        """Run the grouped dataset's block with one task's values replaced.
        Returns (result, that task)."""
        grouped, _resources, po = self.make_grouped()
        real = blocks.compute
        geom_id = self.fms[0].geom_id

        def compute_with_injected_values(*args, **kwargs):
            produced, failures = real(*args, **kwargs)
            produced[(geom_id, po.id)] = {"mean": values_by_pos}
            return produced, failures

        with mock.patch.object(blocks, "compute", side_effect=compute_with_injected_values), \
                override_settings(EXTRACT_BLOCK_DATASETS=[grouped.id]):
            (result,) = self.run_all()
        return result, ExtractTask.objects.get(dataset_id=grouped.id, po=po, fm=self.fms[0])

    def test_nul_in_names_and_scalar_values_fails_only_affected_tasks(self):
        real = blocks.compute

        def inject(*args, **kwargs):
            produced, failures = real(*args, **kwargs)
            produced[(self.fms[0].geom_id, self.po_mean.id)] = {"bad\x00name": {0: None}}
            produced[(self.fms[1].geom_id, self.po_mean.id)] = {"mean": {0: "bad\x00value"}}
            return produced, failures

        with mock.patch.object(blocks, "compute", side_effect=inject):
            results = self.run_all(block_size=2)
        self.assertEqual(sum(r["failed"] for r in results), 2)
        self.assertEqual(sum(r["completed"] for r in results), 6)
        for fm, column in zip(self.fms[:2], ("name", "str_value")):
            task = ExtractTask.objects.get(dataset_id=self.dataset.id, fm=fm, po=self.po_mean)
            self.assertIn(f"NUL byte in extract_data.{column}", task.error)
            self.assertFalse(
                ExtractData.objects.filter(dataset_id=self.dataset.id, extract_task=task).exists()
            )

    def test_nul_in_string_array_fails_only_affected_task(self):
        result, task = self.run_grouped_with({0: None, 1: "bad\x00value"})
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["completed"], 3)
        self.assertIn("NUL byte in extract_data.str_values", task.error)
        self.assertFalse(
            ExtractData.objects.filter(dataset_id=task.dataset_id, extract_task=task).exists()
        )

    def test_a_mixed_type_array_is_stored_as_the_per_task_path_stores_it(self):
        values_by_pos = {0: 1, 1: 2.5}
        result, task = self.run_grouped_with(values_by_pos)

        self.assertEqual(result["completed"], 4)
        row = ExtractData.objects.get(dataset_id=task.dataset_id, extract_task=task)

        # The same values through the per-task path's bulk_create.
        ((_name, field, value),) = data_values({"mean": values_by_pos}, 2, "reference")
        reference = ExtractData(dataset_id=task.dataset_id, extract_task=task, name="reference")
        setattr(reference, field, value)
        ExtractData.objects.bulk_create([reference])
        reference = ExtractData.objects.get(
            dataset_id=task.dataset_id, extract_task=task, name="reference"
        )
        for column in blocks._DATA_COLUMNS:
            self.assertEqual(getattr(row, column), getattr(reference, column), column)
        self.assertEqual(row.int_values, [1, 2])

    def test_a_value_its_column_cannot_take_fails_only_its_task(self):
        result, task = self.run_grouped_with({0: 1, 1: "abc"})

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["completed"], 3)
        self.assertEqual(task.status, FAILED)
        self.assertIn("expected a number", task.error)
        self.assertFalse(ExtractData.objects.filter(extract_task=task).exists())

    def test_bigint_bounds_fail_only_invalid_tasks_and_allow_later_blocks(self):
        # Test both COPY destinations, including valid endpoints, and put
        # the failures first so completing later blocks proves progress.
        for grouped in (False, True):
            with self.subTest(grouped=grouped):
                if grouped:
                    dataset, resources, po = self.make_grouped()
                else:
                    dataset, resources, po = self.dataset, [self.resource], self.po_mean
                previous = ExtractTask.objects.create(
                    dataset_id=dataset.id, resource_ids=[r.id for r in resources],
                    fm=self.fms[0], po=po, status=FAILED,
                )
                ExtractData.objects.create(
                    dataset_id=dataset.id, extract_task=previous,
                    name="previous", int_value=42,
                )
                values = (2**63, -(2**63) - 1, -(2**63), 2**63 - 1)
                real = blocks.compute

                def inject(*args, **kwargs):
                    produced, failures = real(*args, **kwargs)
                    for fm, value in zip(self.fms, values):
                        produced[(fm.geom_id, po.id)] = {
                            "mean": {0: None, 1: value} if grouped else {0: value}
                        }
                    return produced, failures

                with mock.patch.object(blocks, "compute", side_effect=inject), \
                        override_settings(EXTRACT_BLOCK_DATASETS=[dataset.id]):
                    results = self.run_all(block_size=2)
                self.assertEqual(sum(r["failed"] for r in results), 2)
                self.assertEqual(sum(r["completed"] for r in results), 2 if grouped else 6)
                for i, fm in enumerate(self.fms):
                    task = ExtractTask.objects.get(dataset_id=dataset.id, fm=fm, po=po)
                    rows = ExtractData.objects.filter(dataset_id=dataset.id, extract_task=task)
                    if i < 2:
                        self.assertEqual(task.status, FAILED)
                        self.assertIn("out of range", task.error)
                        self.assertEqual(list(rows.values_list("name", "int_value")),
                                         [("previous", 42)] if i == 0 else [])
                    else:
                        self.assertEqual(task.status, DONE)
                        row = rows.get()
                        self.assertEqual(row.int_values if grouped else row.int_value,
                                         [None, values[i]] if grouped else values[i])
                progress = ExtractTaskBuildProgress.objects.get(
                    po=po, resource_ids=[r.id for r in resources]
                )
                self.assertGreaterEqual(progress.computed_up_to_fm_id, self.fms[-1].id)
                self.assertIsNone(progress.block_claim_token)

    def test_numeric_conversion_overflow_fails_only_its_task(self):
        result, task = self.run_grouped_with({0: 1, 1: float("inf")})

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["completed"], 3)
        self.assertEqual(task.status, FAILED)
        self.assertIn("OverflowError", task.error)
        self.assertFalse(ExtractData.objects.filter(
            dataset_id=task.dataset_id, extract_task=task
        ).exists())

    def test_the_fence_runs_after_the_task_writes(self):
        sync_progress_pairs()
        with CaptureQueriesContext(connection) as ctx:
            run_block()
        sqls = [q["sql"] for q in ctx.captured_queries]

        def last(fragment):
            return max(i for i, sql in enumerate(sqls) if fragment in sql)

        fence = last("SET computed_up_to_fm_id")
        self.assertGreater(fence, last("UPDATE extract_tasks"))
        self.assertGreater(fence, last("INSERT INTO extract_tasks"))
        self.assertGreater(fence, last("INSERT INTO extract_data"))

    def test_a_concurrent_builder_batch_does_not_deadlock(self):
        # The builder's batch inserts extract_tasks rows, then updates its
        # pair's progress row, in one transaction. When the block's insert
        # waits on one of those rows, the builder must still be able to take
        # the progress row -- which it cannot if the block's fence holds it.
        sync_progress_pairs()
        pair = self.progress(self.po_mean)
        inserted, errors = threading.Event(), []

        def builder_batch():
            try:
                with transaction.atomic():
                    ExtractTask.objects.create(
                        dataset_id=self.dataset.id, resource_ids=[self.resource.id],
                        fm=self.fms[0], po=self.po_mean, status=PENDING,
                    )
                    inserted.set()
                    # Wait until the block is blocked on that row.
                    with connection.cursor() as cursor:
                        wait_for_a_blocked_backend(cursor)
                    ExtractTaskBuildProgress.objects.filter(id=pair.id).update(
                        completed_up_to_fm_id=self.fms[0].id
                    )
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        writer = threading.Thread(target=builder_batch)
        writer.start()
        self.assertTrue(inserted.wait(10))
        result = run_block()
        writer.join(10)

        self.assertEqual(errors, [])
        self.assertNotIn("error", result)
        # The builder's row won the race and keeps its own (pending) state.
        self.assertEqual(result["unavailable"], 1)
        self.assertEqual(result["completed"], 7)
        pair.refresh_from_db()
        self.assertEqual(pair.completed_up_to_fm_id, self.fms[0].id)
        self.assertEqual(pair.computed_up_to_fm_id, FeatMap.objects.order_by("-id").first().id)

    def test_the_builder_coexists_with_blocks(self):
        self.run_all()
        _build_extract_tasks()
        self.assertEqual(ExtractTask.objects.filter(dataset_id=self.dataset.id).count(), 8)
        self.assertFalse(ExtractTask.objects.filter(status=PENDING).exists())


class BlockLeaseTests(BlockTestCase):
    def test_a_live_lease_is_not_claimed_twice(self):
        sync_progress_pairs()
        self.assertIsNotNone(claim_block())
        self.assertIsNone(claim_block())

    def test_concurrent_claims_take_different_resources(self):
        DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r2", path="r2.tif",
            temporal=datetime(2020, 2, 1, tzinfo=timezone.utc),
        )
        sync_progress_pairs()
        first, second = claim_block(), claim_block()
        self.assertNotEqual(first.resource_ids, second.resource_ids)
        self.assertFalse(set(first.pair_ids) & set(second.pair_ids))

    def test_a_claim_between_its_statements_does_not_split_the_resource(self):
        # A claimer that has locked its seed row but not yet its siblings.
        # Unserialized, a second claimer skips the locked seed, seeds on the
        # same resource's next option and leases that alone -- two blocks,
        # each reading the raster for part of the options.
        #
        # Synced once per resource so the first resource's pairs have the two
        # lowest ids: the pair after the seed is then its own sibling.
        sync_progress_pairs()
        DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r2", path="r2.tif",
            temporal=datetime(2020, 2, 1, tzinfo=timezone.utc),
        )
        sync_progress_pairs()
        params = {"lease_minutes": 10, "datasets": []}
        max_fm_id = FeatMap.objects.order_by("-id").first().id
        seeded, first, errors = threading.Event(), {}, []

        def first_claimer():
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(%s)", [blocks.BLOCK_CLAIM_LOCK_ID]
                    )
                    cursor.execute(blocks._SEED_SQL, {**params, "max_fm_id": max_fm_id})
                    _seed_id, resource_ids, lo, dataset_id, _period = cursor.fetchone()
                    seeded.set()
                    wait_for_a_blocked_backend(cursor, timeout=5)
                    cursor.execute(blocks._SIBLINGS_SQL, {
                        **params, "dataset_id": dataset_id,
                        "resource_ids": resource_ids, "lo": lo,
                    })
                    pair_ids = [row[0] for row in cursor.fetchall()]
                    cursor.execute(blocks._LEASE_SQL, [uuid.uuid4(), pair_ids])
                    first.update(resource_ids=list(resource_ids), pair_ids=pair_ids)
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        claimer = threading.Thread(target=first_claimer)
        claimer.start()
        self.assertTrue(seeded.wait(10))
        second = claim_block()
        claimer.join(15)

        self.assertEqual(errors, [])
        self.assertNotEqual(second.resource_ids, first["resource_ids"])
        self.assertEqual(len(second.options), 2)
        self.assertEqual(len(first["pair_ids"]), 2)

    def test_an_expired_lease_is_taken_over(self):
        sync_progress_pairs()
        stale = claim_block()
        ExtractTaskBuildProgress.objects.update(
            block_claimed_at=datetime(2000, 1, 1, tzinfo=timezone.utc)
        )
        fresh = claim_block()
        self.assertEqual(set(fresh.pair_ids), set(stale.pair_ids))
        self.assertNotEqual(fresh.token, stale.token)

    def test_an_option_behind_the_rest_forms_its_own_block(self):
        self.run_all()
        po_min = self.make_po(self.dataset, "min")
        sync_progress_pairs()
        block = claim_block()
        self.assertEqual([po_id for po_id, *_ in block.options], [po_min.id])

    def test_a_lost_lease_writes_nothing(self):
        real = blocks.compute

        def compute_then_lose(*args, **kwargs):
            ExtractTaskBuildProgress.objects.update(block_claim_token=uuid.uuid4())
            return real(*args, **kwargs)

        sync_progress_pairs()
        lost_before = blocks_counted("lost")
        with mock.patch.object(blocks, "compute", side_effect=compute_then_lose):
            result = run_block()

        self.assertEqual(result, {"lost": True})
        self.assertEqual(blocks_counted("lost") - lost_before, 1)
        self.assertFalse(ExtractTask.objects.exists())
        self.assertIsNone(self.progress(self.po_mean).computed_up_to_fm_id)

    def test_the_heartbeat_extends_the_lease_and_detects_its_loss(self):
        sync_progress_pairs()
        block = claim_block()
        heartbeat = blocks._LeaseHeartbeat(block, interval=60)
        ExtractTaskBuildProgress.objects.update(
            block_claimed_at=datetime(2000, 1, 1, tzinfo=timezone.utc)
        )
        self.assertTrue(heartbeat._beat())
        self.assertGreater(
            self.progress(self.po_mean).block_claimed_at.year, 2000
        )
        ExtractTaskBuildProgress.objects.update(block_claim_token=uuid.uuid4())
        self.assertFalse(heartbeat._beat())
        self.assertTrue(heartbeat.lost)

    def test_the_heartbeat_reconnects_after_losing_its_connection(self):
        # A dropped connection stays dropped until something closes it; left
        # alone, every later beat fails on it and the lease expires under a
        # block that is still computing.
        self.addCleanup(connection.close)
        sync_progress_pairs()
        block = claim_block()
        heartbeat = blocks._LeaseHeartbeat(block, interval=60)
        ExtractTaskBuildProgress.objects.update(
            block_claimed_at=datetime(2000, 1, 1, tzinfo=timezone.utc)
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            (pid,) = cursor.fetchone()

        def terminate():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
            finally:
                connection.close()

        killer = threading.Thread(target=terminate)
        killer.start()
        killer.join(10)

        with self.assertLogs("analytics.blocks", level="WARNING") as logs:
            self.assertTrue(heartbeat._beat())
        self.assertIn("heartbeat failed", logs.output[0])
        self.assertFalse(heartbeat.lost)

        self.assertTrue(heartbeat._beat())
        self.assertGreater(self.progress(self.po_mean).block_claimed_at.year, 2000)

    def test_the_write_starts_on_a_fresh_lease(self):
        # The last beat can be most of an interval old by the time compute
        # ends; the write must not start on what is left of it.
        real_compute, real_write = blocks.compute, blocks.write_block
        seen = {}

        def compute_then_age_the_lease(*args, **kwargs):
            result = real_compute(*args, **kwargs)
            ExtractTaskBuildProgress.objects.update(
                block_claimed_at=datetime(2000, 1, 1, tzinfo=timezone.utc)
            )
            return result

        def write_recording_the_lease(*args, **kwargs):
            seen["claimed_at"] = self.progress(self.po_mean).block_claimed_at
            return real_write(*args, **kwargs)

        sync_progress_pairs()
        with mock.patch.object(blocks, "compute", side_effect=compute_then_age_the_lease), \
                mock.patch.object(blocks, "write_block", side_effect=write_recording_the_lease):
            result = run_block()

        self.assertEqual(result["completed"], 8)
        self.assertGreater(seen["claimed_at"].year, 2000)

    def test_heartbeat_refreshes_from_another_connection_during_write(self):
        real_heartbeat = blocks._LeaseHeartbeat
        real_refresh, real_write = blocks.refresh_lease, blocks._write_tasks
        writing, refreshed = threading.Event(), threading.Event()
        writer_thread = threading.get_ident()

        def refresh(block):
            held = real_refresh(block)
            if writing.is_set() and threading.get_ident() != writer_thread and held:
                refreshed.set()
            return held

        def write(cursor, block, tasks, data):
            counts = real_write(cursor, block, tasks, data)
            writing.set()
            self.assertTrue(refreshed.wait(5), "no heartbeat during write transaction")
            self.assertIsNone(claim_block(), "a live write must not be taken over")
            return counts

        sync_progress_pairs()
        with mock.patch.object(blocks, "_LeaseHeartbeat", side_effect=lambda b: real_heartbeat(b, 0.01)), \
                mock.patch.object(blocks, "refresh_lease", side_effect=refresh), \
                mock.patch.object(blocks, "_write_tasks", side_effect=write):
            result = run_block()
        self.assertEqual(result["completed"], 8)

    def test_heartbeat_after_commit_does_not_report_a_lost_block(self):
        real_heartbeat, real_write = blocks._LeaseHeartbeat, blocks.write_block
        heartbeats = []

        def heartbeat(block):
            instance = real_heartbeat(block)
            heartbeats.append(instance)
            return instance

        def write(*args, **kwargs):
            counts = real_write(*args, **kwargs)
            self.assertFalse(heartbeats[0]._beat())
            return counts

        sync_progress_pairs()
        lost_before = blocks_counted("lost")
        with mock.patch.object(blocks, "_LeaseHeartbeat", side_effect=heartbeat), \
                mock.patch.object(blocks, "write_block", side_effect=write):
            result = run_block()
        self.assertEqual(result["completed"], 8)
        self.assertEqual(blocks_counted("lost"), lost_before)

    def test_an_error_backs_the_block_off(self):
        sync_progress_pairs()
        errors_before = blocks_counted("error")
        with mock.patch.object(blocks, "compute", side_effect=RuntimeError("boom")):
            result = run_block()

        self.assertTrue(result["error"])
        self.assertEqual(blocks_counted("error") - errors_before, 1)
        progress = self.progress(self.po_mean)
        self.assertIsNotNone(progress.block_claim_token)
        self.assertIsNone(progress.computed_up_to_fm_id)
        # Still leased, so the next chain moves on rather than failing on it
        # again...
        self.assertIsNone(claim_block())
        # ...until the lease expires.
        ExtractTaskBuildProgress.objects.update(
            block_claimed_at=datetime(2000, 1, 1, tzinfo=timezone.utc)
        )
        self.assertIsNotNone(claim_block())

    def test_a_written_block_is_counted(self):
        before = blocks_counted("written")
        self.run_all()
        self.assertEqual(blocks_counted("written") - before, 1)


class BlockTaskTests(SimpleTestCase):
    @override_settings(EXTRACT_BLOCKS_ENABLED=True)
    def test_a_block_with_work_chains_exactly_one_successor(self):
        from analytics.tasks import blocks as block_tasks

        with mock.patch("analytics.blocks.run_block", return_value={"completed": 1}), \
                mock.patch.object(block_tasks.run_extract_block, "delay") as delay:
            block_tasks.run_extract_block()
        delay.assert_called_once_with()

    @override_settings(EXTRACT_BLOCKS_ENABLED=True)
    def test_an_empty_claim_ends_the_chain(self):
        from analytics.tasks import blocks as block_tasks

        with mock.patch("analytics.blocks.run_block", return_value=None), \
                mock.patch.object(block_tasks.run_extract_block, "delay") as delay:
            block_tasks.run_extract_block()
        delay.assert_not_called()

    @override_settings(EXTRACT_BLOCKS_ENABLED=True)
    def test_a_failed_block_still_chains_a_successor(self):
        from analytics.tasks import blocks as block_tasks

        with mock.patch("analytics.blocks.run_block", return_value={"error": True}), \
                mock.patch.object(block_tasks.run_extract_block, "delay") as delay:
            block_tasks.run_extract_block()
        delay.assert_called_once_with()

    @override_settings(EXTRACT_BLOCKS_ENABLED=True)
    def test_a_failed_claim_ends_the_chain(self):
        from analytics.tasks import blocks as block_tasks

        with mock.patch("analytics.blocks.run_block", side_effect=RuntimeError("db down")), \
                mock.patch.object(block_tasks.run_extract_block, "delay") as delay:
            with self.assertRaises(RuntimeError):
                block_tasks.run_extract_block()
        delay.assert_not_called()

    @override_settings(EXTRACT_BLOCKS_ENABLED=False)
    def test_disabled_blocks_do_nothing(self):
        from analytics.tasks import blocks as block_tasks

        with mock.patch("analytics.blocks.run_block") as run, \
                mock.patch.object(block_tasks.run_extract_block, "delay") as delay:
            block_tasks.run_extract_block()
            result = block_tasks.dispatch_block_chains()
        run.assert_not_called()
        delay.assert_not_called()
        self.assertEqual(result["dispatched"], 0)

    @override_settings(EXTRACT_BLOCKS_ENABLED=True)
    def test_the_beat_fills_idle_block_slots(self):
        from analytics.tasks import blocks as block_tasks

        with mock.patch(
            "analytics.management.commands.build_extract_tasks.sync_progress_pairs"
        ) as sync, mock.patch(
            "analytics.tasks.maintenance._idle_slots", return_value=(["w"], 8, 3)
        ) as idle, mock.patch.object(block_tasks.run_extract_block, "delay") as delay:
            result = block_tasks.dispatch_block_chains()

        sync.assert_called_once_with()
        idle.assert_called_once_with("analytics.tasks.blocks.run_extract_block")
        self.assertEqual(delay.call_count, 5)
        self.assertEqual(result["dispatched"], 5)


class BuilderSwitchTests(BlockTestCase):
    @override_settings(EXTRACT_TASK_BUILDER_GLOBAL_ENABLED=False)
    def test_a_disabled_builder_builds_no_global_tasks_from_any_entry_point(self):
        # The management command and trigger_coverage_and_extract's inline
        # fallback call _build_extract_tasks; a build_extract_tasks_worker
        # message queued before the flag flipped calls _build_global_tasks.
        with mock.patch(
            "analytics.management.commands.build_extract_tasks._build_non_global_tasks",
            return_value=0,
        ) as non_global:
            result = _build_extract_tasks()
        self.assertEqual(_build_global_tasks(), 0)

        non_global.assert_called_once()
        self.assertEqual(result["added"], 0)
        self.assertFalse(ExtractTask.objects.exists())

    def test_an_enabled_builder_builds_global_tasks(self):
        self.assertEqual(_build_global_tasks(), 8)

    @override_settings(EXTRACT_TASK_BUILDER_GLOBAL_ENABLED=False)
    def test_a_disabled_builder_skips_the_global_wave(self):
        from analytics.tasks import maintenance

        with mock.patch(
            "analytics.management.commands.build_extract_tasks.try_acquire_build_run"
        ) as acquire, mock.patch.object(
            maintenance.build_extract_tasks_worker, "delay"
        ) as delay:
            maintenance.build_extract_tasks()

        acquire.assert_not_called()
        delay.assert_not_called()

    def test_the_idle_slot_helper_routes_by_task_queue(self):
        from analytics.tasks import maintenance

        inspector = mock.Mock(
            active_queues=mock.Mock(return_value={
                "proc@a": [{"name": "processing"}],
                "blk@b": [{"name": "blocks"}],
            }),
            stats=mock.Mock(return_value={
                "proc@a": {"pool": {"max-concurrency": 4}},
                "blk@b": {"pool": {"max-concurrency": 6}},
            }),
            active=mock.Mock(return_value={
                "blk@b": [{"name": "analytics.tasks.blocks.run_extract_block"}],
            }),
            reserved=mock.Mock(return_value={}),
        )
        with mock.patch("celery.current_app.control.inspect", return_value=inspector):
            workers, total, in_flight = maintenance._idle_slots(
                "analytics.tasks.blocks.run_extract_block"
            )
        self.assertEqual((workers, total, in_flight), (["blk@b"], 6, 1))


class BenchmarkCommandTests(BlockTestCase):
    def test_reports_identical_values_and_rolls_back_the_write(self):
        from io import StringIO

        from django.core.management import call_command

        sync_progress_pairs()
        out = StringIO()
        call_command(
            "benchmark_extract_block", resource=self.resource.id, write=True, stdout=out
        )

        output = out.getvalue()
        self.assertIn("values identical", output)
        self.assertIn("write: 8 tasks", output)
        self.assertFalse(ExtractTask.objects.exists())
        self.assertFalse(ExtractData.objects.exists())
        progress = self.progress(self.po_mean)
        self.assertIsNone(progress.computed_up_to_fm_id)
        self.assertIsNone(progress.block_claim_token)
