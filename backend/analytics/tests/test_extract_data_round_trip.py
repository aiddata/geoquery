from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase

from analytics.models import ExtractData, ExtractTask, ProcessingOption, Request, RequestMap
from analytics.tasks import processing
from analytics.tasks.merge import merge_task_results
from analytics.tasks.processing import _run_extract_task
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin
from visualize.data import build_request_data


class ExtractDataRoundTripTest(ReplicaReadsTestMixin, TestCase):
    """Writer -> storage -> BOTH readers, with no hand-built rows anywhere.

    Every other test in this area either mocks the writer or constructs
    ExtractData rows by hand, so nothing else checks that what the writer
    actually produces is what the readers actually consume. That contract is
    exactly what the scalar/array split and the nodata-as-NULL change
    rewrote, and it spans three files that are otherwise tested in isolation.

    The nodata case here goes through a processor returning Python None --
    the real path, since that is what rasterstats returns for a feature with
    no valid pixels. It used to be stored as the string 'None', which slipped
    past merge's `is None` guard and reached user downloads as text.
    """

    def setUp(self):
        self.ds = Dataset.objects.create(name="ds1", path="/d", active=True, short_name="DS1")
        self.po = ProcessingOption.objects.create(
            dataset=self.ds, short_name="mean",
            function="rasterstats_default_mean", active=True)
        self.fc = FeatureCollection.objects.create(name="fc1", path="/f", active=True)
        self.r = DatasetResource.objects.create(dataset=self.ds, name="res", path="r0.tif")

    def _task(self, feat):
        fm = FeatMap.objects.create(fc=self.fc, geom=feat, name="F", attr={})
        return ExtractTask.objects.create(
            resource_ids=[self.r.id], dataset_id=self.ds.id, fm=fm, po=self.po, status=3)

    def test_writer_output_is_read_correctly_by_merge_and_visualize(self):
        good_feat = Feature.objects.create(shape=Point(0, 0))
        nodata_feat = Feature.objects.create(shape=Point(1, 1))
        good, nodata = self._task(good_feat), self._task(nodata_feat)

        with mock.patch.object(processing, "get_func",
                               return_value=lambda g, p, **kw: [("mean", 7.5)]):
            _run_extract_task(good.id)
        # The real nodata path: the processor returns None, as rasterstats does.
        with mock.patch.object(processing, "get_func",
                               return_value=lambda g, p, **kw: [("mean", None)]):
            _run_extract_task(nodata.id)

        # Storage: scalar written, arrays untouched, nodata all-NULL.
        g = ExtractData.objects.get(extract_task_id=good.id, name="mean")
        n = ExtractData.objects.get(extract_task_id=nodata.id, name="mean")
        self.assertEqual(g.float_value, 7.5)
        self.assertIsNone(g.float_values)
        for f in ("int_value", "float_value", "str_value",
                  "int_values", "float_values", "str_values"):
            self.assertIsNone(getattr(n, f), f"{f} should be NULL for nodata")

        # Reader 1: merge. The nodata cell must be NaN, never the text "None".
        status, df = merge_task_results({good.id: self.ds.id, nodata.id: self.ds.id})
        self.assertEqual(status, "Success")
        col = df.set_index("geom_id")["res.mean"]
        self.assertEqual(col[good_feat.id], 7.5)
        self.assertTrue(col[nodata_feat.id] != col[nodata_feat.id])  # NaN
        self.assertNotIn("None", df["res.mean"].astype(str).tolist())

        # Reader 2: visualize.
        req = Request.objects.create(contact="a@b.c", source="web_custom", status=1, data={})
        RequestMap.objects.bulk_create([
            RequestMap(request=req, task_id=t.id, dataset_id=self.ds.id)
            for t in (good, nodata)])
        payload = build_request_data(req)
        feats = payload["features"]
        self.assertEqual(feats[str(good_feat.id)]["res.mean"], 7.5)
        self.assertIsNone(feats[str(nodata_feat.id)]["res.mean"])
