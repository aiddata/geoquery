from django.test import TestCase

from datasets.models import Dataset, DatasetResource
from features.models import FeatureCollection
from stac_api.sources import (
    all_collection_sources,
    get_collection_source,
    get_item,
    get_items_for_collection,
    item_stac_id,
)


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


class GetCollectionSourceTests(TestCase):
    def test_finds_a_dataset_by_name(self):
        make_dataset(name="ds-one", path="ds-one")
        self.assertIsInstance(get_collection_source("ds-one"), Dataset)

    def test_finds_a_feature_collection_by_name(self):
        make_feature_collection(name="fc-one", path="fc-one")
        self.assertIsInstance(get_collection_source("fc-one"), FeatureCollection)

    def test_returns_none_when_not_found(self):
        self.assertIsNone(get_collection_source("does-not-exist"))

    def test_ignores_inactive_dataset(self):
        make_dataset(name="hidden", path="hidden", active=False)
        self.assertIsNone(get_collection_source("hidden"))

    def test_ignores_private_feature_collection(self):
        make_feature_collection(name="hidden-fc", path="hidden-fc", public=False)
        self.assertIsNone(get_collection_source("hidden-fc"))

    def test_dataset_wins_the_tiebreak_on_a_name_collision(self):
        make_dataset(name="shared-name", path="ds-path")
        make_feature_collection(name="shared-name", path="fc-path")

        self.assertIsInstance(get_collection_source("shared-name"), Dataset)


class AllCollectionSourcesTests(TestCase):
    def test_combines_datasets_and_feature_collections(self):
        make_dataset(name="ds-one", path="ds-one")
        make_feature_collection(name="fc-one", path="fc-one")

        names = {s.name for s in all_collection_sources()}

        self.assertEqual(names, {"ds-one", "fc-one"})

    def test_excludes_inactive_and_private(self):
        make_dataset(name="visible", path="visible")
        make_dataset(name="hidden", path="hidden", active=False)

        names = {s.name for s in all_collection_sources()}

        self.assertEqual(names, {"visible"})

    def test_orders_combined_results_by_name_interleaved(self):
        make_dataset(name="b-thing", path="b-thing")
        make_feature_collection(name="a-thing", path="a-thing")
        make_dataset(name="c-thing", path="c-thing")

        names = [s.name for s in all_collection_sources()]

        self.assertEqual(names, ["a-thing", "b-thing", "c-thing"])


class GetItemsForCollectionTests(TestCase):
    def test_returns_dataset_resources_for_a_dataset(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-2020", path="/x/2020.tif")

        items = get_items_for_collection(dataset)

        self.assertEqual([i.name for i in items], ["ds-one-2020"])

    def test_returns_a_single_synthetic_item_for_a_feature_collection(self):
        fc = make_feature_collection(name="fc-one", path="fc-one")

        self.assertEqual(get_items_for_collection(fc), [fc])


class ItemStacIdTests(TestCase):
    def test_dataset_resource_uses_its_own_name(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        resource = DatasetResource.objects.create(dataset=dataset, name="ds-one-2020", path="/x/2020.tif")

        self.assertEqual(item_stac_id(resource), "ds-one-2020")

    def test_feature_collection_gets_a_synthetic_suffix(self):
        fc = make_feature_collection(name="fc-one", path="fc-one")

        self.assertEqual(item_stac_id(fc), "fc-one-item")


class GetItemTests(TestCase):
    def test_finds_a_dataset_resource_item_by_stac_id(self):
        dataset = make_dataset(name="ds-one", path="ds-one")
        DatasetResource.objects.create(dataset=dataset, name="ds-one-2020", path="/x/2020.tif")

        item = get_item(dataset, "ds-one-2020")

        self.assertIsNotNone(item)
        self.assertEqual(item.name, "ds-one-2020")

    def test_finds_the_synthetic_boundary_item(self):
        fc = make_feature_collection(name="fc-one", path="fc-one")

        self.assertEqual(get_item(fc, "fc-one-item"), fc)

    def test_returns_none_when_item_not_found(self):
        dataset = make_dataset(name="ds-one", path="ds-one")

        self.assertIsNone(get_item(dataset, "nope"))
