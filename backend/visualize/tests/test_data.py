from django.contrib.gis.geos import Point
from django.test import TestCase

from analytics.models import ExtractData, ExtractTask, ProcessingOption, Request, RequestMap
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection
from visualize.data import build_explore_available, build_explore_data, build_request_data


class VisualizeDataTestCase(TestCase):
    """build_request_data / build_explore_data / build_explore_available against
    the resource_ids/*_values array schema (see analytics.models.ExtractTask/
    ExtractData docstrings for the position-alignment invariant these queries
    reconstruct one-row-per-resource from via unnest(...) WITH ORDINALITY).
    """

    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset.objects.create(
            name="ds1", path="/data/ds1", active=True, short_name="DS1", title="Dataset One",
        )
        cls.po = ProcessingOption.objects.create(
            dataset=cls.dataset,
            short_name="mean",
            description="units: mm",
            function="rasterstats_default_mean",
            active=True,
        )
        cls.fc = FeatureCollection.objects.create(name="fc1", path="/data/fc1", active=True)
        cls.feature = Feature.objects.create(shape=Point(0, 0))
        cls.fm = FeatMap.objects.create(
            fc=cls.fc, geom=cls.feature, name="Feature A", attr={"iso": "ABC"}
        )

    def _make_request(self, *tasks):
        req = Request.objects.create(contact="a@example.com", source="web_custom", status=1, data={})
        RequestMap.objects.bulk_create(
            RequestMap(request=req, task_id=t.id, dataset_id=self.dataset.id) for t in tasks
        )
        return req

    # --- standard (1-element resource_ids) task -----------------------------

    def test_build_request_data_standard_task(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds1-r1", label="Jan 2020", path="r1.tif"
        )
        task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[12.5],
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="count",
            data_column="int", int_values=[5],
        )
        req = self._make_request(task)

        result = build_request_data(req)

        self.assertEqual(result["columns"], ["ds1-r1.count", "ds1-r1.mean"])
        self.assertEqual(result["col_groups"], {"ds1-r1": ["ds1-r1.count", "ds1-r1.mean"]})
        self.assertEqual(result["col_temporal"], {"ds1-r1.mean": "Jan 2020", "ds1-r1.count": "Jan 2020"})
        self.assertEqual(
            result["col_dataset_titles"],
            {"ds1-r1.mean": "DS1", "ds1-r1.count": "DS1"},
        )
        self.assertEqual(result["col_descriptions"], {"ds1-r1.mean": "units: mm", "ds1-r1.count": "units: mm"})

        feature_record = result["features"][str(self.feature.id)]
        self.assertEqual(feature_record["name"], "Feature A")
        self.assertEqual(feature_record["boundary.iso"], "ABC")
        self.assertEqual(feature_record["ds1-r1.mean"], 12.5)
        self.assertIsInstance(feature_record["ds1-r1.mean"], float)
        self.assertEqual(feature_record["ds1-r1.count"], 5)
        self.assertIsInstance(feature_record["ds1-r1.count"], int)

        self.assertEqual(result["request_id"], str(req.id))
        self.assertEqual(result["bbox"], [0.0, 0.0, 0.0, 0.0])

    # --- grouped multi-resource task: N values -> N attributed entries ------

    def test_build_request_data_grouped_task_attributes_each_resource(self):
        resources = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"ds1-grp-{i}", label=f"2020-{i:02d}", path=f"g{i}.tif"
            )
            for i in (1, 2, 3)
        ]
        task = ExtractTask.objects.create(
            resource_ids=[r.id for r in resources],
            dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[10.0, 20.0, 30.0],
        )
        req = self._make_request(task)

        result = build_request_data(req)

        # Each of the 3 resource_ids positions must land as its own column,
        # attributed to its own DatasetResource's name -- not merged/overwritten.
        self.assertEqual(
            result["columns"],
            ["ds1-grp-1.mean", "ds1-grp-2.mean", "ds1-grp-3.mean"],
        )
        feature_record = result["features"][str(self.feature.id)]
        self.assertEqual(feature_record["ds1-grp-1.mean"], 10.0)
        self.assertEqual(feature_record["ds1-grp-2.mean"], 20.0)
        self.assertEqual(feature_record["ds1-grp-3.mean"], 30.0)
        self.assertEqual(
            result["col_temporal"],
            {"ds1-grp-1.mean": "2020-01", "ds1-grp-2.mean": "2020-02", "ds1-grp-3.mean": "2020-03"},
        )

    def test_build_request_data_grouped_task_with_null_position(self):
        # A position that's still NULL (not yet processed, or its resource
        # failed -- see analytics.tasks.processing) must come back as None,
        # not be dropped or mistakenly attributed to a neighboring resource.
        resources = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"ds1-null-{i}", path=f"n{i}.tif"
            )
            for i in (1, 2)
        ]
        task = ExtractTask.objects.create(
            resource_ids=[r.id for r in resources],
            dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=-1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[None, 7.5],
        )
        req = self._make_request(task)

        result = build_request_data(req)

        feature_record = result["features"][str(self.feature.id)]
        self.assertIsNone(feature_record["ds1-null-1.mean"])
        self.assertEqual(feature_record["ds1-null-2.mean"], 7.5)

    def test_build_request_data_str_value_and_kwargs_filter_desc(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds1-str", path="s.tif"
        )
        task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id, fm=self.fm, po=self.po,
            status=1, kwargs={"threshold": {"type": "range", "start": 1, "end": 5}},
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="majority",
            data_column="str", str_values=["forest"],
        )
        req = self._make_request(task)

        result = build_request_data(req)

        feature_record = result["features"][str(self.feature.id)]
        self.assertEqual(feature_record["ds1-str.majority"], "forest")
        self.assertEqual(result["col_filter_desc"], {"ds1-str.majority": "threshold: 1–5"})

    # --- explore data (same flattening, filtered by fc/po instead of request)

    def test_build_explore_data_grouped_task_attributes_each_resource(self):
        resources = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"ds1-exp-{i}", path=f"e{i}.tif"
            )
            for i in (1, 2)
        ]
        task = ExtractTask.objects.create(
            resource_ids=[r.id for r in resources],
            dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[100.0, 200.0],
        )
        # Not linked via RequestMap at all -- build_explore_data must not
        # require one.
        result = build_explore_data([self.fc.id], [self.po.id])

        self.assertEqual(result["columns"], ["ds1-exp-1.mean", "ds1-exp-2.mean"])
        feature_record = result["features"][str(self.feature.id)]
        self.assertEqual(feature_record["ds1-exp-1.mean"], 100.0)
        self.assertEqual(feature_record["ds1-exp-2.mean"], 200.0)
        self.assertNotIn("request_id", result)

    def test_build_explore_data_filters_by_fc_and_po(self):
        other_po = ProcessingOption.objects.create(
            dataset=self.dataset, short_name="other", function="rasterstats_default_mean", active=True,
        )
        resource = DatasetResource.objects.create(dataset=self.dataset, name="ds1-filt", path="f.tif")
        matching_task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=matching_task, dataset_id=self.dataset.id, name="mean",
            data_column="float", float_values=[1.0],
        )
        other_task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id, fm=self.fm, po=other_po, status=1,
        )
        ExtractData.objects.create(
            extract_task=other_task, dataset_id=self.dataset.id, name="other",
            data_column="float", float_values=[2.0],
        )

        result = build_explore_data([self.fc.id], [self.po.id])

        self.assertEqual(result["columns"], ["ds1-filt.mean"])

    # --- explore available: dataset/po grouping ------------------------------

    def test_build_explore_available_groups_by_dataset_and_po(self):
        ds_b = Dataset.objects.create(
            name="ds_b", path="/data/ds_b", active=True, short_name=None, title="Dataset B",
        )
        po_b = ProcessingOption.objects.create(
            dataset=ds_b, short_name="sum", description="", function="rasterstats_default_sum", active=True,
        )
        resource_a = DatasetResource.objects.create(dataset=self.dataset, name="ds1-avail", path="a.tif")
        resource_b = DatasetResource.objects.create(dataset=ds_b, name="dsb-avail", path="b.tif")

        ExtractTask.objects.create(
            resource_ids=[resource_a.id], dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=1,
        )
        ExtractTask.objects.create(
            resource_ids=[resource_b.id], dataset_id=ds_b.id, fm=self.fm, po=po_b, status=1,
        )
        # A pending (not yet completed) task must not show up as "available".
        pending_po = ProcessingOption.objects.create(
            dataset=self.dataset, short_name="pending", function="rasterstats_default_mean", active=True,
        )
        ExtractTask.objects.create(
            resource_ids=[resource_a.id], dataset_id=self.dataset.id, fm=self.fm, po=pending_po, status=0,
        )

        result = build_explore_available([self.fc.id], [self.po.id, po_b.id, pending_po.id])

        self.assertEqual(len(result), 2)
        by_id = {row["dataset_id"]: row for row in result}

        self.assertEqual(by_id[self.dataset.id]["dataset_title"], "Dataset One")
        self.assertEqual(
            by_id[self.dataset.id]["options"],
            [{"po_id": self.po.id, "short_name": "mean", "description": "units: mm"}],
        )

        self.assertEqual(by_id[ds_b.id]["dataset_title"], "Dataset B")
        self.assertEqual(
            by_id[ds_b.id]["options"],
            [{"po_id": po_b.id, "short_name": "sum", "description": ""}],
        )

        # Ordered by dataset title ("Dataset B" < "Dataset One").
        self.assertEqual([row["dataset_id"] for row in result], [ds_b.id, self.dataset.id])

    def test_build_explore_available_falls_back_to_name_without_title(self):
        ds_no_title = Dataset.objects.create(
            name="ds_no_title", path="/data/ds_no_title", active=True, title=None,
        )
        po2 = ProcessingOption.objects.create(
            dataset=ds_no_title, short_name="mean", function="rasterstats_default_mean", active=True,
        )
        resource = DatasetResource.objects.create(dataset=ds_no_title, name="ntr", path="nt.tif")
        ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=ds_no_title.id, fm=self.fm, po=po2, status=1,
        )

        result = build_explore_available([self.fc.id], [po2.id])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dataset_title"], "ds_no_title")
