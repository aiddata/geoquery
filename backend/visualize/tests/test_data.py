from django.contrib.gis.geos import Point
from django.test import TestCase

from analytics.models import (
    ExtractData, ExtractTask, ExtractTaskBuildProgress, ProcessingOption, Request, RequestMap,
)
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin
from visualize.data import build_explore_available, build_explore_data, build_request_data


class VisualizeDataTestCase(ReplicaReadsTestMixin, TestCase):
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
            float_values=[12.5],
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="count",
            int_values=[5],
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
            float_values=[10.0, 20.0, 30.0],
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

    def test_build_request_data_keeps_only_the_requested_positions(self):
        # A request for two months links the bucket's task, which holds all
        # three; the visualization shows only the months asked for.
        resources = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"ds1-req-{i}", path=f"q{i}.tif"
            )
            for i in (1, 2, 3)
        ]
        task = ExtractTask.objects.create(
            resource_ids=[r.id for r in resources],
            dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            float_values=[10.0, 20.0, 30.0],
        )
        req = self._make_request(task)
        req.data = {"datasets": [{"dataset_name": "ds1", "resource_ids": [resources[0].id, resources[2].id]}]}
        req.save(update_fields=["data"])

        result = build_request_data(req)

        self.assertEqual(result["columns"], ["ds1-req-1.mean", "ds1-req-3.mean"])

    def test_build_request_data_grouped_task_with_null_position(self):
        # A NULL position in a completed task is nodata, and must come back
        # as None, not be dropped or mistakenly attributed to a neighboring
        # resource.
        resources = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"ds1-null-{i}", path=f"n{i}.tif"
            )
            for i in (1, 2)
        ]
        task = ExtractTask.objects.create(
            resource_ids=[r.id for r in resources],
            dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            float_values=[None, 7.5],
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
            str_values=["forest"],
        )
        req = self._make_request(task)

        result = build_request_data(req)

        feature_record = result["features"][str(self.feature.id)]
        self.assertEqual(feature_record["ds1-str.majority"], "forest")
        self.assertEqual(result["col_filter_desc"], {"ds1-str.majority": "threshold: 1–5"})

    # --- scalar rows -------------------------------------------------------

    def test_build_request_data_scalar_row_is_not_dropped_by_unnest(self):
        # Scalar rows have NULL arrays, and multi-arg unnest pads shorter
        # arrays with NULL to match resource_ids' length -- so without the
        # COALESCE wrapping, the row still comes out but its value column
        # is NULL, silently reading as nodata rather than failing loudly.
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds1-r1", label="Jan 2020", path="r1.tif"
        )
        task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id,
            fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            float_value=3.25,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="count",
            int_value=7,
        )
        req = self._make_request(task)

        result = build_request_data(req)

        record = result["features"][str(self.feature.id)]
        self.assertEqual(record["ds1-r1.mean"], 3.25)
        self.assertIsInstance(record["ds1-r1.mean"], float)
        self.assertEqual(record["ds1-r1.count"], 7)
        self.assertIsInstance(record["ds1-r1.count"], int)

    def test_build_request_data_all_null_row_yields_none(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds1-r1", label="Jan 2020", path="r1.tif"
        )
        task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id,
            fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
        )
        req = self._make_request(task)

        result = build_request_data(req)

        self.assertIsNone(result["features"][str(self.feature.id)]["ds1-r1.mean"])

    # --- explore data (same flattening, filtered by fc/po instead of request)

    def test_failed_and_unfinished_tasks_are_not_served(self):
        # Only completed results are live: a failed task's surviving
        # positions, or a task still pending a rerun, must not reach a viewer.
        resource = DatasetResource.objects.create(dataset=self.dataset, name="ds1-nl", path="nl.tif")
        for status, value in ((-1, 1.0), (0, 2.0)):
            task = ExtractTask.objects.create(
                resource_ids=[resource.id], dataset_id=self.dataset.id, fm=self.fm,
                po=self.po, status=status, kwargs={"status": status},
            )
            ExtractData.objects.create(
                extract_task=task, dataset_id=self.dataset.id, name=f"mean_{status}",
                float_value=value,
            )
            req = self._make_request(task)
            self.assertEqual(build_request_data(req)["columns"], [])
        self.assertEqual(build_explore_data([self.fc.id], [self.po.id])["columns"], [])

    def test_a_pending_reset_hides_exactly_the_results_it_names(self):
        resource = DatasetResource.objects.create(dataset=self.dataset, name="ds1-hide", path="h.tif")
        other_fm = FeatMap.objects.create(fc=self.fc, geom=Feature.objects.create(shape=Point(1, 1)), name="B")
        tasks = []
        for fm in (self.fm, other_fm):
            task = ExtractTask.objects.create(
                resource_ids=[resource.id], dataset_id=self.dataset.id, fm=fm, po=self.po, status=1)
            ExtractData.objects.create(extract_task=task, dataset_id=self.dataset.id, name="mean", float_value=1.0)
            tasks.append(task)
        req = self._make_request(*tasks)
        # Feature A is reshaped: its results wait for sync, B's stay served.
        Feature.objects.filter(id=self.feature.id).update(shape=Point(5, 5))
        for payload in (build_request_data(req), build_explore_data([self.fc.id], [self.po.id])):
            self.assertNotIn("ds1-hide.mean", payload["features"][str(self.feature.id)])
            self.assertEqual(payload["features"][str(other_fm.geom_id)]["ds1-hide.mean"], 1.0)

    def test_grouped_results_of_a_retired_pair_are_not_explored(self):
        resources = [
            DatasetResource.objects.create(dataset=self.dataset, name=f"ds1-old-{i}", path=f"o{i}.tif")
            for i in (1, 2)
        ]
        retired = ExtractTaskBuildProgress.objects.create(
            resource_ids=[r.id for r in resources], po=self.po, dataset_id=self.dataset.id,
            current=False,
        )
        task = ExtractTask.objects.create(
            resource_ids=[r.id for r in resources], dataset_id=self.dataset.id, fm=self.fm,
            po=self.po, status=1, pair_id=retired.id,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean", float_values=[1.0, 2.0],
        )
        self.assertEqual(build_explore_data([self.fc.id], [self.po.id])["columns"], [])
        self.assertEqual(build_explore_available([self.fc.id], [self.po.id]), [])
        # A request built from that set still shows it.
        self.assertEqual(
            build_request_data(self._make_request(task))["columns"],
            ["ds1-old-1.mean", "ds1-old-2.mean"],
        )

    def test_a_current_pairs_grouped_value_wins_over_a_singleton_request_task(self):
        resources = [
            DatasetResource.objects.create(dataset=self.dataset, name=f"ds1-pref-{i}", path=f"p{i}.tif")
            for i in (1, 2)
        ]
        pair = ExtractTaskBuildProgress.objects.create(
            resource_ids=[r.id for r in resources], po=self.po, dataset_id=self.dataset.id,
            current=True,
        )
        grouped = ExtractTask.objects.create(
            resource_ids=[r.id for r in resources], dataset_id=self.dataset.id, fm=self.fm,
            po=self.po, status=1, pair_id=pair.id,
        )
        ExtractData.objects.create(
            extract_task=grouped, dataset_id=self.dataset.id, name="mean", float_values=[10.0, 20.0],
        )
        singleton = ExtractTask.objects.create(
            resource_ids=[resources[0].id], dataset_id=self.dataset.id, fm=self.fm,
            po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=singleton, dataset_id=self.dataset.id, name="mean", float_value=99.0,
        )
        record = build_explore_data([self.fc.id], [self.po.id])["features"][str(self.feature.id)]
        self.assertEqual(record["ds1-pref-1.mean"], 10.0)
        self.assertEqual(record["ds1-pref-2.mean"], 20.0)

    def test_build_explore_data_grouped_task_attributes_each_resource(self):
        resources = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"ds1-exp-{i}", path=f"e{i}.tif"
            )
            for i in (1, 2)
        ]
        pair = ExtractTaskBuildProgress.objects.create(
            resource_ids=[r.id for r in resources], po=self.po, dataset_id=self.dataset.id,
            current=True,
        )
        task = ExtractTask.objects.create(
            resource_ids=[r.id for r in resources],
            dataset_id=self.dataset.id, fm=self.fm, po=self.po, status=1, pair_id=pair.id,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            float_values=[100.0, 200.0],
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
            float_values=[1.0],
        )
        other_task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id, fm=self.fm, po=other_po, status=1,
        )
        ExtractData.objects.create(
            extract_task=other_task, dataset_id=self.dataset.id, name="other",
            float_values=[2.0],
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
