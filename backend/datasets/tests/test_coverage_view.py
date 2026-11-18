"""POST /api/datasets/coverage/: datasets for a selection, and which of the
selected boundary sets each one covers (GEO-127)."""

from django.test import TestCase

from analytics.models import Coverage
from datasets.models import Dataset
from features.models import Feature, FeatMap, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin


def dataset(name, is_global=False):
    return Dataset.objects.create(name=name, path=f"/{name}", type="raster", title=name,
                                  is_global=is_global, active=True, public=True)


class DatasetCoverageViewTests(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        self.sets = []
        self.features = {}
        for name in ("gB_x_GHA_ADM1", "gB_x_GHA_ADM2", "gB_x_TZA_ADM1"):
            fc = FeatureCollection.objects.create(name=name, path=f"/{name}", active=True, public=True)
            self.sets.append(fc)
            self.features[fc.id] = []
            for _ in range(2):
                feature = Feature.objects.create(shape="POINT(0 0)")
                FeatMap.objects.create(fc=fc, geom=feature)
                self.features[fc.id].append(feature)
        self.ids = [f.id for fs in self.features.values() for f in fs]
        self.fc_ids = [fc.id for fc in self.sets]
        self.world = dataset("world", is_global=True)
        self.ghana = dataset("ghana")
        gha1, gha2, _ = self.sets
        # Ghana covers one feature of each Ghana set and nothing in Tanzania
        for fc in (gha1, gha2):
            Coverage.objects.create(geom=self.features[fc.id][0], dataset=self.ghana, status=1)
        # A status-0 row does not count as coverage
        Coverage.objects.create(geom=self.features[self.sets[2].id][0], dataset=self.ghana, status=0)

    def post(self, body):
        response = self.client.post("/api/datasets/coverage/", body, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return {d["name"]: d for d in response.json()}

    def test_each_dataset_lists_the_selected_sets_it_covers(self):
        result = self.post({"featureIds": self.ids, "fcIds": self.fc_ids})
        self.assertEqual(result["world"]["covered_boundary_sets"], self.fc_ids)
        self.assertEqual(result["ghana"]["covered_boundary_sets"], self.fc_ids[:2])

    def test_sets_follow_the_order_given(self):
        reordered = list(reversed(self.fc_ids))
        result = self.post({"featureIds": self.ids, "fcIds": reordered})
        self.assertEqual(result["ghana"]["covered_boundary_sets"], reordered[1:])

    def test_only_selected_features_count(self):
        # Ghana ADM2 narrowed to the feature Ghana does not cover
        gha2 = self.sets[1]
        result = self.post({"featureIds": [self.features[gha2.id][1].id], "fcIds": [gha2.id]})
        self.assertNotIn("ghana", result)
        self.assertEqual(result["world"]["covered_boundary_sets"], [gha2.id])

    def test_without_fc_ids_the_field_is_left_out(self):
        result = self.post({"featureIds": self.ids})
        self.assertEqual(set(result), {"world", "ghana"})
        self.assertNotIn("covered_boundary_sets", result["ghana"])

    def test_fc_ids_must_be_integers(self):
        response = self.client.post(
            "/api/datasets/coverage/", {"featureIds": self.ids, "fcIds": ["a"]}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
