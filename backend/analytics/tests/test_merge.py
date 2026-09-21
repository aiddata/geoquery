from unittest import mock

import pandas as pd
from django.contrib.gis.geos import Point
from django.test import TestCase

from analytics.models import ExtractData, ExtractTask, ProcessingOption
from analytics.tasks.merge import merge_task_results
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection


class MergeTaskResultsTestCase(TestCase):
    """merge_task_results against the resource_ids/*_values array schema (see
    analytics.models.ExtractTask/ExtractData docstrings for the
    position-alignment invariant this function reconstructs per-resource
    columns from).
    """

    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset.objects.create(name="ds1", path="/data/ds1", active=True)
        cls.po = ProcessingOption.objects.create(
            dataset=cls.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
        )
        cls.fc = FeatureCollection.objects.create(name="fc1", path="/data/fc1", active=True)
        cls.feature = Feature.objects.create(shape=Point(0, 0))
        cls.fm = FeatMap.objects.create(
            fc=cls.fc, geom=cls.feature, name="Feature A", attr={"iso": "ABC"}
        )

    def make_task(self, resources, *, status=1, **kwargs):
        return ExtractTask.objects.create(
            resource_ids=[r.id for r in resources],
            dataset_id=self.dataset.id,
            fm=self.fm,
            po=self.po,
            status=status,
            **kwargs,
        )

    def key(self):
        return ("fc1", self.feature.id)

    # --- standard 1-element task ---------------------------------------

    def test_standard_task_single_resource(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="my_resource", path="r1.tif"
        )
        task = self.make_task([resource])
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[12.5],
        )

        status, df = merge_task_results({task.id: self.dataset.id})

        self.assertEqual(status, "Success")
        row = df.iloc[0]
        self.assertEqual(row["feature_collection"], "fc1")
        self.assertEqual(row["geom_id"], self.feature.id)
        self.assertEqual(row["boundary.iso"], "ABC")
        self.assertEqual(row["my_resource.mean"], 12.5)

    # --- grouped multi-resource task, N-way expansion --------------------

    def test_grouped_task_expands_each_resource_into_its_own_column(self):
        # resources created in ascending DB id order (r0, r1, r2) but
        # resource_ids below deliberately uses a different order -- this
        # proves position alignment follows task.resource_ids, not the
        # id__in query's (arbitrary) DB order. A regression that drops the
        # by_id reindex would attribute values to the wrong resource.
        r0, r1, r2 = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"grp-{i}", path=f"g{i}.tif"
            )
            for i in range(3)
        ]
        task = self.make_task([r2, r0, r1])
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[20.0, 0.0, 10.0],
        )

        status, df = merge_task_results({task.id: self.dataset.id})

        self.assertEqual(status, "Success")
        row = df.iloc[0]
        self.assertEqual(row["grp-2.mean"], 20.0)
        self.assertEqual(row["grp-0.mean"], 0.0)
        self.assertEqual(row["grp-1.mean"], 10.0)

    # --- None at a position is skipped, not errored or placeholder'd -----

    def test_null_position_is_skipped_not_placeholder(self):
        r0, r1 = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"null-{i}", path=f"n{i}.tif"
            )
            for i in range(2)
        ]
        task = self.make_task([r0, r1], status=-1)
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[None, 7.5],
        )

        status, df = merge_task_results({task.id: self.dataset.id})

        self.assertEqual(status, "Success")
        row = df.iloc[0]
        # Column for the None position must not exist at all (not NaN via an
        # explicit write, just genuinely absent from that row's dict) --
        # pandas fills it in as NaN only because the column exists for
        # other rows; here there's only one row so the column shouldn't
        # even appear.
        self.assertNotIn("null-0.mean", df.columns)
        self.assertEqual(row["null-1.mean"], 7.5)

    # --- None-at-position mixed into a multi-row DataFrame becomes a
    # genuine NaN, not a dropped column or fabricated placeholder ----------

    def test_null_position_becomes_nan_when_other_row_has_a_value(self):
        r0, r1 = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"null2-{i}", path=f"m{i}.tif"
            )
            for i in range(2)
        ]
        task_a = self.make_task([r0, r1], status=-1)
        ExtractData.objects.create(
            extract_task=task_a, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[None, 7.5],
        )

        # A second feature/task where null2-0 DOES have a value, so the
        # column genuinely exists in the merged DataFrame -- this is what
        # lets us confirm pandas fills task_a's missing cell with NaN
        # rather than dropping the column or otherwise mishandling the
        # ragged dict-to-DataFrame construction.
        feature_b = Feature.objects.create(shape=Point(1, 1))
        fm_b = FeatMap.objects.create(
            fc=self.fc, geom=feature_b, name="Feature B", attr={"iso": "XYZ"}
        )
        task_b = ExtractTask.objects.create(
            resource_ids=[r0.id, r1.id],
            dataset_id=self.dataset.id,
            fm=fm_b,
            po=self.po,
            status=1,
        )
        ExtractData.objects.create(
            extract_task=task_b, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[3.5, 9.0],
        )

        status, df = merge_task_results({task_a.id: self.dataset.id, task_b.id: self.dataset.id})

        self.assertEqual(status, "Success")
        self.assertIn("null2-0.mean", df.columns)

        row_a = df[df["geom_id"] == self.feature.id].iloc[0]
        row_b = df[df["geom_id"] == feature_b.id].iloc[0]

        # task_a's skipped position becomes a genuine NaN cell...
        self.assertTrue(pd.isna(row_a["null2-0.mean"]))
        self.assertEqual(row_a["null2-1.mean"], 7.5)
        # ...while task_b's real value for that same column is untouched.
        self.assertEqual(row_b["null2-0.mean"], 3.5)
        self.assertEqual(row_b["null2-1.mean"], 9.0)

    # --- "_none" outcome substitution, applied per-resource ---------------

    def test_none_suffix_outcome_substitution_applies_per_resource(self):
        r_sub, r_plain = [
            DatasetResource.objects.create(
                dataset=self.dataset, name="acled_none", path="a.tif"
            ),
            DatasetResource.objects.create(
                dataset=self.dataset, name="other_resource", path="b.tif"
            ),
        ]
        task = self.make_task([r_sub, r_plain], kwargs={"outcome": "event_count"})
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[1.0, 2.0],
        )

        status, df = merge_task_results({task.id: self.dataset.id})

        self.assertEqual(status, "Success")
        row = df.iloc[0]
        self.assertEqual(row["acled_event_count.mean"], 1.0)
        self.assertEqual(row["other_resource.mean"], 2.0)
        self.assertNotIn("acled_none.mean", df.columns)

    # --- int/str typed columns coerce correctly ---------------------------

    def test_int_and_str_data_columns(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="typed_resource", path="t.tif"
        )
        task = self.make_task([resource])
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="count",
            data_column="int", int_values=[5],
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="majority",
            data_column="str", str_values=["forest"],
        )

        status, df = merge_task_results({task.id: self.dataset.id})

        self.assertEqual(status, "Success")
        row = df.iloc[0]
        self.assertEqual(row["typed_resource.count"], 5)
        self.assertEqual(row["typed_resource.majority"], "forest")

    # --- unsupported data_column still raises ------------------------------

    def test_unsupported_data_column_raises(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="bad_resource", path="b.tif"
        )
        task = self.make_task([resource])
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="weird",
            data_column="bogus",
        )

        with self.assertRaises(Exception) as cm:
            merge_task_results({task.id: self.dataset.id})
        self.assertIn("Unsupported data column type", str(cm.exception))

    # --- missing task still raises ------------------------------------------

    def test_missing_task_raises(self):
        with self.assertRaises(Exception) as cm:
            merge_task_results({999999: self.dataset.id})
        self.assertIn("not found", str(cm.exception))

    # --- empty task list returns Empty --------------------------------------

    def test_empty_task_list_returns_empty(self):
        status, df = merge_task_results({})
        self.assertEqual(status, "Empty")
        self.assertIsNone(df)


class MergeQueryCountTestCase(TestCase):
    """The merge must not issue queries proportional to the task count.

    It used to run five per task -- ExtractTask, ExtractData, FeatMap,
    FeatureCollection, DatasetResource. Each is ~0.1ms, so the cost was never
    the queries themselves but the round trips: measured in production, a
    1040-task request spent 3h38m in this function, ~2.5s per round trip,
    because every one of them had to wait for a pooler server slot that the
    extract-task claim storm was holding.
    """

    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset.objects.create(name="ds1", path="/data/ds1", active=True)
        cls.other = Dataset.objects.create(name="ds2", path="/data/ds2", active=True)
        cls.po = ProcessingOption.objects.create(
            dataset=cls.dataset, short_name="mean",
            function="rasterstats_default_mean", active=True,
        )
        cls.fc = FeatureCollection.objects.create(
            name="fc1", path="/data/fc1", active=True
        )

    def build(self, dataset, n, *, start=0):
        """n tasks on `dataset`, each its own feature, one ExtractData row each."""
        resource = DatasetResource.objects.create(
            dataset=dataset, name=f"res_{dataset.id}_{start}", path=f"r_{dataset.id}_{start}.tif"
        )
        task_map = {}
        for i in range(n):
            feature = Feature.objects.create(shape=Point(start + i, 0))
            fm = FeatMap.objects.create(
                fc=self.fc, geom=feature, name=f"F{start + i}"
            )
            task = ExtractTask.objects.create(
                resource_ids=[resource.id], dataset_id=dataset.id,
                fm=fm, po=self.po, status=1, kwargs={"n": start + i},
            )
            ExtractData.objects.create(
                extract_task=task, dataset_id=dataset.id, name="mean",
                data_column="float", float_values=[float(start + i)],
            )
            task_map[task.id] = dataset.id
        return task_map

    def test_query_count_does_not_grow_with_task_count(self):
        small = self.build(self.dataset, 2)
        with self.assertNumQueries(5) as ctx:
            status, df = merge_task_results(small)
        self.assertEqual(status, "Success")
        self.assertEqual(len(df), 2)
        baseline = len(ctx.captured_queries)

        big = self.build(self.dataset, 20, start=100)
        with self.assertNumQueries(baseline):
            status, df = merge_task_results(big)
        self.assertEqual(status, "Success")
        self.assertEqual(len(df), 20)

    def test_each_dataset_stays_pruned(self):
        task_map = {**self.build(self.dataset, 3), **self.build(self.other, 3, start=50)}

        with self.assertNumQueries(7) as ctx:
            status, df = merge_task_results(task_map)

        self.assertEqual(status, "Success")
        self.assertEqual(len(df), 6)
        # Every extract_tasks/extract_data query must carry dataset_id, or it
        # scans all 57 partitions instead of seeking one.
        partitioned = [
            q["sql"] for q in ctx.captured_queries
            if "extract_task" in q["sql"] or "extract_data" in q["sql"]
        ]
        self.assertTrue(partitioned)
        for sql in partitioned:
            self.assertIn("dataset_id", sql, f"unpruned query: {sql[:200]}")


    def test_chunking_reuses_cached_collections_and_resources(self):
        # Chunking is what bounds memory for the 61k-task requests that exist
        # in production. Feature collections and dataset resources are cached
        # for the whole merge, so a second chunk must not re-fetch them: only
        # the per-task queries repeat.
        from analytics.tasks import merge as merge_module

        task_map = self.build(self.dataset, 6, start=500)

        with mock.patch.object(merge_module, "MERGE_CHUNK_SIZE", 2):
            # 3 chunks x (tasks + data + featmaps), plus collections and
            # resources fetched exactly once for the whole merge.
            with self.assertNumQueries(3 * 3 + 1 + 1) as ctx:
                status, df = merge_task_results(task_map)

        self.assertEqual(status, "Success")
        self.assertEqual(len(df), 6)

        sql = [q["sql"] for q in ctx.captured_queries]
        self.assertEqual(
            sum(1 for q in sql if "feature_collections" in q), 1,
            "feature collections were re-fetched per chunk",
        )
        self.assertEqual(
            sum(1 for q in sql if "dataset_resources" in q), 1,
            "dataset resources were re-fetched per chunk",
        )


class MergeTaskFeaturesQueryCountTestCase(TestCase):
    """merge_task_features ran three queries per feature (FeatMap,
    FeatureCollection, Feature) on top of merge_task_results' five per task."""

    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset.objects.create(name="ds1", path="/data/ds1", active=True)
        cls.po = ProcessingOption.objects.create(
            dataset=cls.dataset, short_name="mean",
            function="rasterstats_default_mean", active=True,
        )
        cls.fc = FeatureCollection.objects.create(
            name="fc1", path="/data/fc1", active=True
        )
        cls.resource = DatasetResource.objects.create(
            dataset=cls.dataset, name="res", path="r.tif"
        )

    def build(self, n, *, start=0):
        task_map = {}
        for i in range(n):
            fm = FeatMap.objects.create(
                fc=self.fc,
                geom=Feature.objects.create(shape=Point(start + i, 0)),
                name=f"F{start + i}",
            )
            task = ExtractTask.objects.create(
                resource_ids=[self.resource.id], dataset_id=self.dataset.id,
                fm=fm, po=self.po, status=1, kwargs={"n": start + i},
            )
            task_map[task.id] = self.dataset.id
        return task_map

    def test_query_count_does_not_grow_with_feature_count(self):
        from analytics.tasks.merge import merge_task_features

        small = self.build(2)
        with self.assertNumQueries(4) as ctx:
            status, gdf = merge_task_features(small)
        self.assertEqual(status, "Success")
        self.assertEqual(len(gdf), 2)
        baseline = len(ctx.captured_queries)

        big = self.build(20, start=100)
        with self.assertNumQueries(baseline):
            status, gdf = merge_task_features(big)
        self.assertEqual(status, "Success")
        self.assertEqual(len(gdf), 20)

    def test_still_returns_empty_when_nothing_matches(self):
        from analytics.tasks.merge import merge_task_features

        self.assertEqual(merge_task_features({}), ("Empty", None))
