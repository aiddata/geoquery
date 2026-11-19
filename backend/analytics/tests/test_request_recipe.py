"""GET /api/analytics/requests/<id>/recipe/: a past request as a recipe for
"Use as template" (GEO-126), and fc_ids recorded on new requests."""

from django.test import TestCase

from analytics.models import Coverage, ProcessingOption, Request
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin


def make_set(name, n=2):
    fc = FeatureCollection.objects.create(name=name, title=name.upper(), path=f"/{name}", active=True, public=True)
    features = []
    for _ in range(n):
        feature = Feature.objects.create(shape="POINT(0 0)")
        FeatMap.objects.create(fc=fc, geom=feature)
        features.append(feature.id)
    return fc, features


def raster(name, is_global=True, resources=("2020", "2021"), measures=("mean", "max")):
    ds = Dataset.objects.create(name=name, title=f"{name} title", path=f"/{name}", type="raster",
                                is_global=is_global, active=True, public=True)
    for r in resources:
        DatasetResource.objects.create(dataset=ds, name=f"{name}_{r}", label=r, path=f"{r}.tif")
    for m in measures:
        ProcessingOption.objects.create(dataset=ds, short_name=m, function=f"rasterstats_default_{m}",
                                        active=True, public=True)
    return ds


def spec(name, measures, years, **extra):
    return {"datasetName": name, "datasetType": "raster", "extractTypes": list(measures),
            "resources": [f"{name}_{y}" for y in years], "resourceLabels": list(years), **extra}


class RequestRecipeTests(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        self.adm1, self.adm1_features = make_set("gha_adm1")
        self.adm2, self.adm2_features = make_set("gha_adm2", n=3)
        self.ntl = raster("ntl")

    def make_request(self, feature_ids, datasets, **data):
        return Request.objects.create(contact="a@example.org", status=1, data={
            "feature_ids": feature_ids, "dataset_specs": datasets, **data})

    def get(self, req, expect=200):
        response = self.client.get(f"/api/analytics/requests/{req.id}/recipe/")
        self.assertEqual(response.status_code, expect, response.content)
        return response.json()

    def test_whole_sets_are_worked_out_from_the_features(self):
        req = self.make_request(self.adm1_features + self.adm2_features, [spec("ntl", ["mean"], ["2020"])])
        body = self.get(req)
        self.assertEqual(body["recipe"]["v"], 1)
        self.assertEqual(body["recipe"]["boundaries"], {"fcIds": [self.adm1.id, self.adm2.id], "featureIds": []})
        self.assertEqual([fc["name"] for fc in body["boundary_sets"]], ["gha_adm1", "gha_adm2"])
        self.assertEqual(body["dropped"], {"features": 0, "datasets": [], "options": []})

    def test_recorded_sets_are_used_in_their_order(self):
        req = self.make_request(self.adm1_features + self.adm2_features, [],
                                fc_ids=[self.adm2.id, self.adm1.id])
        self.assertEqual(self.get(req)["recipe"]["boundaries"]["fcIds"], [self.adm2.id, self.adm1.id])

    def test_part_of_one_set_is_that_set_narrowed(self):
        some = self.adm2_features[:2]
        req = self.make_request(some, [])
        self.assertEqual(self.get(req)["recipe"]["boundaries"], {"fcIds": [self.adm2.id], "featureIds": some})
        # Recorded the same way on a new request
        req = self.make_request(some, [], fc_ids=[self.adm2.id])
        self.assertEqual(self.get(req)["recipe"]["boundaries"], {"fcIds": [self.adm2.id], "featureIds": some})

    def test_features_that_are_not_a_whole_set_are_dropped(self):
        req = self.make_request(self.adm1_features + self.adm2_features[:1], [])
        body = self.get(req)
        self.assertEqual(body["recipe"]["boundaries"]["fcIds"], [self.adm1.id])
        self.assertEqual(body["dropped"]["features"], 1)

    def test_a_raster_becomes_a_cart_item(self):
        req = self.make_request(self.adm1_features, [spec("ntl", ["mean"], ["2020", "2021"])])
        [item] = self.get(req)["recipe"]["datasets"]
        self.assertEqual(item, {
            "customName": "ntl title", "datasetName": "ntl", "datasetTitle": "ntl title",
            "datasetType": "raster", "processingClass": "zonal_stats",
            "extractTypes": ["mean"], "resources": ["ntl_2020", "ntl_2021"], "resourceLabels": ["2020", "2021"],
        })

    def test_a_raster_with_no_time_periods_is_kept(self):
        # Temporally invariant rasters are requested with no periods at all
        raster("elevation", resources=("static",))
        req = self.make_request(self.adm1_features, [
            {"datasetName": "elevation", "datasetType": "raster", "extractTypes": ["mean"], "resources": []}])
        body = self.get(req)
        [item] = body["recipe"]["datasets"]
        self.assertEqual((item["datasetName"], item["extractTypes"], item["resources"]), ("elevation", ["mean"], []))
        self.assertEqual(body["dropped"]["datasets"], [])

    def test_removed_periods_and_measures_are_left_out_and_listed(self):
        req = self.make_request(self.adm1_features, [spec("ntl", ["mean", "median"], ["2020", "1999"])])
        body = self.get(req)
        [item] = body["recipe"]["datasets"]
        self.assertEqual((item["extractTypes"], item["resources"]), (["mean"], ["ntl_2020"]))
        self.assertEqual(body["dropped"]["options"],
                         [{"name": "ntl", "title": "ntl title", "measures": ["median"], "periods": ["1999"]}])

    def test_datasets_that_no_longer_apply_are_listed(self):
        local = raster("local", is_global=False)
        hidden = raster("hidden")
        hidden.public = False
        hidden.save()
        req = self.make_request(self.adm1_features, [
            spec("ntl", ["median"], ["2020"]),  # no measure left
            spec("local", ["mean"], ["2020"]),  # doesn't cover these boundaries
            spec("hidden", ["mean"], ["2020"]),  # not visible
            spec("gone", ["mean"], ["2020"]),  # deleted
        ])
        body = self.get(req)
        self.assertEqual(body["recipe"]["datasets"], [])
        self.assertEqual([(d["name"], d["reason"]) for d in body["dropped"]["datasets"]], [
            ("ntl", "options_removed"), ("local", "not_covered"), ("hidden", "unavailable"), ("gone", "unavailable")])
        # Covered once one of its features is
        Coverage.objects.create(geom_id=self.adm1_features[0], dataset=local, status=1)
        names = [d["datasetName"] for d in self.get(req)["recipe"]["datasets"]]
        self.assertEqual(names, ["local"])

    def test_a_feature_dataset_keeps_its_kwargs_and_filters(self):
        acled = Dataset.objects.create(name="acled", title="ACLED", path="/acled", type="feature",
                                       processing_class="filter_and_agg", is_global=True, active=True, public=True)
        kwargs = {"outcome": "events", "year": {"type": "range", "start": 2019, "end": 2021, "aggregate": True}}
        req = self.make_request(self.adm1_features, [
            {"datasetName": "acled", "datasetType": "feature", "kwargs": kwargs, "name": "acled_recent"}])
        [item] = self.get(req)["recipe"]["datasets"]
        self.assertEqual(item["customName"], "acled_recent")
        self.assertEqual(item["processingClass"], acled.processing_class)
        self.assertEqual(item["kwargs"], kwargs)
        self.assertEqual(item["filterSelections"], {"year": {"type": "range", "start": 2019, "end": 2021}})

    def test_custom_upload_requests_have_no_recipe(self):
        req = self.make_request([], [], is_custom_boundary=True)
        self.get(req, expect=409)

    def test_unknown_request(self):
        response = self.client.get("/api/analytics/requests/00000000-0000-0000-0000-000000000000/recipe/")
        self.assertEqual(response.status_code, 404)


class SubmitRecordsBoundarySetsTests(TestCase):
    def setUp(self):
        self.fc, self.features = make_set("gha_adm1")
        raster("ntl")

    def submit(self, **extra):
        return self.client.post("/api/analytics/requests/", {
            "email": "a@example.org", "featureIds": self.features,
            "datasets": [spec("ntl", ["mean"], ["2020"])], **extra}, content_type="application/json")

    def test_fc_ids_are_stored(self):
        response = self.submit(fcIds=[self.fc.id])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Request.objects.get(id=response.json()["id"]).data["fc_ids"], [self.fc.id])

    def test_fc_ids_are_optional(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(Request.objects.get(id=response.json()["id"]).data["fc_ids"])

    def test_fc_ids_must_be_integers(self):
        self.assertEqual(self.submit(fcIds=["x"]).status_code, 400)
