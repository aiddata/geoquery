from django.contrib.gis.geos import Polygon
from django.test import TestCase
from django.urls import reverse

from datasets.models import Dataset
from features.models import FeatureCollection


def make_dataset(**overrides):
    defaults = dict(
        active=True, public=True, name="test-dataset", path="test-dataset",
        type="raster", title="Test Dataset", description="A test dataset",
        tags=["climate"], source_name="Test Source", source_url="https://example.com",
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


class StacCollectionListViewTests(TestCase):
    def test_returns_collections_and_links_envelope(self):
        make_dataset(name="ds-one", path="ds-one")
        make_feature_collection(name="fc-one", path="fc-one")

        response = self.client.get(reverse("stac_api:collection-list"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        ids = {c["id"] for c in data["collections"]}
        self.assertEqual(ids, {"ds-one", "fc-one"})
        self.assertTrue(data["links"])

    def test_excludes_inactive_and_private(self):
        make_dataset(name="visible", path="visible")
        make_dataset(name="hidden", path="hidden", active=False)

        response = self.client.get(reverse("stac_api:collection-list"))

        ids = {c["id"] for c in response.json()["collections"]}
        self.assertEqual(ids, {"visible"})


class StacCollectionDetailViewTests(TestCase):
    def test_returns_dataset_backed_collection(self):
        make_dataset(name="ds-one", path="ds-one", title="DS One")

        response = self.client.get(
            reverse("stac_api:collection-detail", kwargs={"name": "ds-one"})
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "Collection")
        self.assertEqual(data["id"], "ds-one")
        self.assertEqual(data["title"], "DS One")
        self.assertEqual(data["license"], "proprietary")

    def test_license_and_cite_as_come_from_the_dataset(self):
        make_dataset(
            name="ds-licensed",
            path="ds-licensed",
            license="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            citation="Author, A. (2020). https://doi.org/10.5281/zenodo.12345",
        )

        response = self.client.get(
            reverse("stac_api:collection-detail", kwargs={"name": "ds-licensed"})
        )

        data = response.json()
        self.assertEqual(data["license"], "CC BY 4.0")
        rels = {link["rel"]: link["href"] for link in data["links"]}
        self.assertEqual(
            rels["license"], "https://creativecommons.org/licenses/by/4.0/"
        )
        self.assertEqual(rels["cite-as"], "https://doi.org/10.5281/zenodo.12345")

    def test_no_citation_means_no_cite_as_link(self):
        make_dataset(name="ds-plain", path="ds-plain")

        response = self.client.get(
            reverse("stac_api:collection-detail", kwargs={"name": "ds-plain"})
        )

        rels = {link["rel"] for link in response.json()["links"]}
        self.assertNotIn("cite-as", rels)
        self.assertNotIn("license", rels)

    def test_missing_collection_returns_404(self):
        response = self.client.get(
            reverse("stac_api:collection-detail", kwargs={"name": "does-not-exist"})
        )

        self.assertEqual(response.status_code, 404)

    def test_dataset_without_spatial_extent_gets_whole_world_bbox(self):
        make_dataset(name="ds-one", path="ds-one")

        response = self.client.get(
            reverse("stac_api:collection-detail", kwargs={"name": "ds-one"})
        )

        self.assertEqual(response.json()["extent"]["spatial"]["bbox"], [[-180, -90, 180, 90]])

    def test_feature_collection_includes_summaries_when_group_fields_set(self):
        make_feature_collection(name="fc-one", path="fc-one", group_class="ADM", group_level=2)

        response = self.client.get(
            reverse("stac_api:collection-detail", kwargs={"name": "fc-one"})
        )

        self.assertEqual(
            response.json()["summaries"], {"group_class": ["ADM"], "group_level": [2]}
        )

    def test_feature_collection_omits_summaries_when_group_fields_unset(self):
        make_feature_collection(name="fc-one", path="fc-one")

        response = self.client.get(
            reverse("stac_api:collection-detail", kwargs={"name": "fc-one"})
        )

        self.assertNotIn("summaries", response.json())

    def test_dataset_with_full_metadata_returns_correct_shape(self):
        make_dataset(
            name="ds-full", path="ds-full",
            spatial_extent=Polygon.from_bbox((1, 2, 3, 4)),
            temporal_start="2020-01-01T00:00:00Z",
            temporal_end="2020-12-31T00:00:00Z",
            tags=["climate", "raster"],
            source_name="Test Source",
            source_url="https://example.com",
        )

        response = self.client.get(
            reverse("stac_api:collection-detail", kwargs={"name": "ds-full"})
        )

        data = response.json()
        self.assertEqual(data["extent"]["spatial"]["bbox"], [[1.0, 2.0, 3.0, 4.0]])
        self.assertEqual(
            data["extent"]["temporal"]["interval"],
            [["2020-01-01T00:00:00Z", "2020-12-31T00:00:00Z"]],
        )
        self.assertEqual(data["keywords"], ["climate", "raster"])
        self.assertEqual(
            data["providers"], [{"name": "Test Source", "url": "https://example.com"}]
        )
