from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from datasets.models import Dataset, DatasetResource
from features.models import FeatureCollection


def make_dataset(**overrides):
    defaults = dict(
        active=True, public=True, name="test-dataset", path="test-dataset",
        type="raster", title="Test Dataset",
    )
    defaults.update(overrides)
    return Dataset.objects.create(**defaults)


def make_feature_collection(**overrides):
    defaults = dict(
        active=True, public=True, name="test-boundaries", path="test-boundaries",
        title="Test Boundaries",
    )
    defaults.update(overrides)
    return FeatureCollection.objects.create(**defaults)


class StacItemListViewTests(TestCase):
    def test_returns_itemcollection_envelope(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-2020", path="/x/2020.tif")

        response = self.client.get(
            reverse("stac_api:item-list", kwargs={"name": "ds-one"})
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual([f["id"] for f in data["features"]], ["ds-one-2020"])
        self.assertEqual(data["numberMatched"], 1)
        self.assertEqual(data["numberReturned"], 1)

    def test_unknown_collection_returns_404(self):
        response = self.client.get(
            reverse("stac_api:item-list", kwargs={"name": "does-not-exist"})
        )
        self.assertEqual(response.status_code, 404)

    def test_boundary_collection_has_exactly_one_item(self):
        make_feature_collection(name="fc-one", path="fc-one")

        response = self.client.get(
            reverse("stac_api:item-list", kwargs={"name": "fc-one"})
        )

        data = response.json()
        self.assertEqual(len(data["features"]), 1)
        self.assertEqual(data["features"][0]["id"], "fc-one-item")

    def test_pagination_next_link_present_when_more_items_remain(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-a", path="/x/a.tif")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-b", path="/x/b.tif")

        response = self.client.get(
            reverse("stac_api:item-list", kwargs={"name": "ds-one"}), {"limit": 1}
        )

        rels = {link["rel"] for link in response.json()["links"]}
        self.assertIn("next", rels)

    def test_no_next_link_on_final_page(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-a", path="/x/a.tif")

        response = self.client.get(
            reverse("stac_api:item-list", kwargs={"name": "ds-one"}), {"limit": 100}
        )

        rels = {link["rel"] for link in response.json()["links"]}
        self.assertNotIn("next", rels)


class StacItemDetailViewTests(TestCase):
    def test_returns_dataset_resource_item(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-2020", path="/x/2020.tif")

        response = self.client.get(
            reverse(
                "stac_api:item-detail", kwargs={"name": "ds-one", "item_id": "ds-one-2020"}
            )
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "Feature")
        self.assertEqual(data["id"], "ds-one-2020")
        self.assertEqual(data["collection"], "ds-one")
        self.assertEqual(data["assets"], {})

    def test_via_link_points_at_the_customize_page(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-2020", path="/x/2020.tif")

        response = self.client.get(
            reverse(
                "stac_api:item-detail", kwargs={"name": "ds-one", "item_id": "ds-one-2020"}
            )
        )

        via = next(link for link in response.json()["links"] if link["rel"] == "via")
        self.assertEqual(via["href"], f"{settings.FRONTEND_BASE_URL}/customize")

    def test_unknown_item_returns_404(self):
        make_dataset(name="ds-one", path="ds-one")

        response = self.client.get(
            reverse("stac_api:item-detail", kwargs={"name": "ds-one", "item_id": "nope"})
        )

        self.assertEqual(response.status_code, 404)

    def test_boundary_item(self):
        make_feature_collection(name="fc-one", path="fc-one")

        response = self.client.get(
            reverse(
                "stac_api:item-detail", kwargs={"name": "fc-one", "item_id": "fc-one-item"}
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "fc-one-item")
        self.assertEqual(response.json()["collection"], "fc-one")

    def test_resource_without_own_geometry_or_datetime_falls_back_to_dataset(self):
        from django.contrib.gis.geos import Polygon

        dataset = make_dataset(
            name="ds-one", path="ds-one",
            spatial_extent=Polygon.from_bbox((1, 2, 3, 4)),
            temporal_start="2020-06-01T00:00:00Z",
        )
        DatasetResource.objects.create(dataset=dataset, name="ds-one-2020", path="/x/2020.tif")

        response = self.client.get(
            reverse(
                "stac_api:item-detail", kwargs={"name": "ds-one", "item_id": "ds-one-2020"}
            )
        )

        data = response.json()
        self.assertEqual(data["bbox"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(data["properties"]["datetime"], "2020-06-01T00:00:00Z")
