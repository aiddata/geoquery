from django.contrib.gis.geos import Polygon
from django.test import TestCase
from django.urls import reverse

from datasets.models import Dataset, DatasetResource


def make_dataset(**overrides):
    defaults = dict(
        active=True, public=True, name="test-dataset", path="test-dataset",
        type="raster", title="Test Dataset",
    )
    defaults.update(overrides)
    return Dataset.objects.create(**defaults)


class StacSearchViewTests(TestCase):
    def test_no_params_returns_all_items(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-a", path="/x/a.tif")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-b", path="/x/b.tif")

        response = self.client.get(reverse("stac_api:search"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 2)

    def test_bbox_filters_to_overlapping_items(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-in", path="/x/in.tif",
            spatial_extent=Polygon.from_bbox((0, 0, 10, 10)),
        )
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-out", path="/x/out.tif",
            spatial_extent=Polygon.from_bbox((50, 50, 60, 60)),
        )

        response = self.client.get(reverse("stac_api:search"), {"bbox": "0,0,10,10"})

        ids = {f["id"] for f in response.json()["features"]}
        self.assertEqual(ids, {"ds-one-in"})

    def test_datetime_interval_filters(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-2020", path="/x/2020.tif", temporal="2020-06-01T00:00:00Z"
        )
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-2021", path="/x/2021.tif", temporal="2021-06-01T00:00:00Z"
        )

        response = self.client.get(
            reverse("stac_api:search"),
            {"datetime": "2020-01-01T00:00:00Z/2020-12-31T00:00:00Z"},
        )

        ids = {f["id"] for f in response.json()["features"]}
        self.assertEqual(ids, {"ds-one-2020"})

    def test_open_ended_datetime_interval(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-2020", path="/x/2020.tif", temporal="2020-06-01T00:00:00Z"
        )
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-2021", path="/x/2021.tif", temporal="2021-06-01T00:00:00Z"
        )

        response = self.client.get(
            reverse("stac_api:search"), {"datetime": "2021-01-01T00:00:00Z/.."}
        )

        ids = {f["id"] for f in response.json()["features"]}
        self.assertEqual(ids, {"ds-one-2021"})

    def test_collections_param_restricts_scope(self):
        ds_one = make_dataset(name="ds-one", path="ds-one")
        ds_two = make_dataset(name="ds-two", path="ds-two")
        DatasetResource.objects.create(dataset=ds_one, name="ds-one-a", path="/x/a.tif")
        DatasetResource.objects.create(dataset=ds_two, name="ds-two-a", path="/x/b.tif")

        response = self.client.get(reverse("stac_api:search"), {"collections": "ds-one"})

        ids = {f["id"] for f in response.json()["features"]}
        self.assertEqual(ids, {"ds-one-a"})

    def test_post_accepts_json_body_with_same_filters(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-a", path="/x/a.tif")

        response = self.client.post(
            reverse("stac_api:search"),
            data={"collections": ["ds-one"]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        ids = {f["id"] for f in response.json()["features"]}
        self.assertEqual(ids, {"ds-one-a"})

    def test_bbox_search_finds_item_via_dataset_fallback_geometry(self):
        dataset = make_dataset(
            name="ds-one", path="ds-one",
            spatial_extent=Polygon.from_bbox((0, 0, 10, 10)),
        )
        DatasetResource.objects.create(dataset=dataset, name="ds-one-a", path="/x/a.tif")

        response = self.client.get(reverse("stac_api:search"), {"bbox": "0,0,10,10"})

        ids = {f["id"] for f in response.json()["features"]}
        self.assertEqual(ids, {"ds-one-a"})

    def test_number_matched_exceeds_number_returned_when_limited(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        for i in range(5):
            DatasetResource.objects.create(dataset=dataset, name=f"ds-one-{i}", path=f"/x/{i}.tif")

        response = self.client.get(reverse("stac_api:search"), {"limit": 2})

        data = response.json()
        self.assertEqual(data["numberMatched"], 5)
        self.assertEqual(data["numberReturned"], 2)

    def test_post_accepts_bbox_as_json_array(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-in", path="/x/in.tif",
            spatial_extent=Polygon.from_bbox((0, 0, 10, 10)),
        )

        response = self.client.post(
            reverse("stac_api:search"),
            data={"bbox": [0, 0, 10, 10]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        ids = {f["id"] for f in response.json()["features"]}
        self.assertEqual(ids, {"ds-one-in"})

    def test_unknown_collection_name_returns_empty_not_error(self):
        make_dataset(name="ds-one", path="ds-one")

        response = self.client.get(reverse("stac_api:search"), {"collections": "does-not-exist"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["features"], [])

    def test_combined_bbox_and_datetime_filters(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-match", path="/x/match.tif",
            spatial_extent=Polygon.from_bbox((0, 0, 10, 10)), temporal="2020-06-01T00:00:00Z",
        )
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-wrong-place", path="/x/wp.tif",
            spatial_extent=Polygon.from_bbox((50, 50, 60, 60)), temporal="2020-06-01T00:00:00Z",
        )
        DatasetResource.objects.create(
            dataset=dataset, name="ds-one-wrong-time", path="/x/wt.tif",
            spatial_extent=Polygon.from_bbox((0, 0, 10, 10)), temporal="2021-06-01T00:00:00Z",
        )

        response = self.client.get(
            reverse("stac_api:search"),
            {"bbox": "0,0,10,10", "datetime": "2020-01-01T00:00:00Z/2020-12-31T00:00:00Z"},
        )

        ids = {f["id"] for f in response.json()["features"]}
        self.assertEqual(ids, {"ds-one-match"})

    def test_malformed_bbox_returns_400(self):
        response = self.client.get(reverse("stac_api:search"), {"bbox": "not,a,bbox"})
        self.assertEqual(response.status_code, 400)

    def test_malformed_datetime_returns_400(self):
        response = self.client.get(reverse("stac_api:search"), {"datetime": "not-a-date"})
        self.assertEqual(response.status_code, 400)

    def test_malformed_limit_returns_400(self):
        response = self.client.get(reverse("stac_api:search"), {"limit": "lots"})
        self.assertEqual(response.status_code, 400)
