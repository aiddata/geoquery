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

        status, df = merge_task_results([task.id])

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

        status, df = merge_task_results([task.id])

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

        status, df = merge_task_results([task.id])

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

        status, df = merge_task_results([task_a.id, task_b.id])

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

        status, df = merge_task_results([task.id])

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

        status, df = merge_task_results([task.id])

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
            merge_task_results([task.id])
        self.assertIn("Unsupported data column type", str(cm.exception))

    # --- missing task still raises ------------------------------------------

    def test_missing_task_raises(self):
        with self.assertRaises(Exception) as cm:
            merge_task_results([999999])
        self.assertIn("not found", str(cm.exception))

    # --- empty task list returns Empty --------------------------------------

    def test_empty_task_list_returns_empty(self):
        status, df = merge_task_results([])
        self.assertEqual(status, "Empty")
        self.assertIsNone(df)
