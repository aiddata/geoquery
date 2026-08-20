from django.test import RequestFactory, TestCase
from stac_pydantic import Collection, Item, ItemCollection

from datasets.models import Dataset, DatasetResource
from features.models import FeatureCollection
from stac_api.serializers import CollectionSerializer, ItemSerializer


def make_dataset(**overrides):
    defaults = dict(
        active=True, public=True, name="spec-dataset", path="spec-dataset",
        type="raster", title="Spec Dataset",
    )
    defaults.update(overrides)
    return Dataset.objects.create(**defaults)


def make_feature_collection(**overrides):
    defaults = dict(
        active=True, public=True, name="spec-boundaries", path="spec-boundaries",
        title="Spec Boundaries",
    )
    defaults.update(overrides)
    return FeatureCollection.objects.create(**defaults)


class StacSpecConformanceTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/api/stac/v1/")

    def test_dataset_collection_validates(self):
        dataset = make_dataset()
        data = CollectionSerializer(dataset, context={"request": self.request}).data
        Collection.model_validate(data)

    def test_boundary_collection_validates(self):
        fc = make_feature_collection()
        data = CollectionSerializer(fc, context={"request": self.request}).data
        Collection.model_validate(data)

    def test_dataset_resource_item_validates(self):
        dataset = make_dataset()
        resource = DatasetResource.objects.create(
            dataset=dataset, name="spec-dataset-2020", path="/x/2020.tif"
        )
        data = ItemSerializer(resource, context={"request": self.request}).data
        Item.model_validate(data)

    def test_boundary_item_validates(self):
        fc = make_feature_collection()
        data = ItemSerializer(fc, context={"request": self.request}).data
        Item.model_validate(data)

    def test_item_list_response_validates_as_itemcollection(self):
        dataset = make_dataset()
        DatasetResource.objects.create(dataset=dataset, name="spec-dataset-2020", path="/x/2020.tif")

        response = self.client.get(f"/api/stac/v1/collections/{dataset.name}/items/")

        ItemCollection.model_validate(response.json())

    def test_search_response_validates_as_itemcollection(self):
        dataset = make_dataset()
        DatasetResource.objects.create(dataset=dataset, name="spec-dataset-2020", path="/x/2020.tif")

        response = self.client.get("/api/stac/v1/search/")

        ItemCollection.model_validate(response.json())
