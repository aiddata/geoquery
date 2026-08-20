from django.test import TestCase
from django.urls import reverse

from analytics.models import Coverage
from datasets.models import Dataset
from features.models import Feature
from public_api.serializers import PublicDatasetSerializer

EXPECTED_DATASET_FIELDS = {
    "name",
    "title",
    "description",
    "type",
    "tags",
    "source_name",
    "source_url",
    "temporal_name",
    "temporal_type",
    "temporal_start",
    "temporal_end",
    "date_updated",
    "bbox",
}


def make_dataset(**overrides):
    defaults = dict(
        active=True,
        public=True,
        name="test-dataset",
        path="test-dataset",
        type="raster",
        title="Test Dataset",
    )
    defaults.update(overrides)
    return Dataset.objects.create(**defaults)


class PublicDatasetSerializerTests(TestCase):
    def test_field_stability(self):
        dataset = make_dataset()

        data = PublicDatasetSerializer(dataset).data

        self.assertEqual(set(data.keys()), EXPECTED_DATASET_FIELDS)

    def test_bbox_is_none_without_spatial_extent(self):
        dataset = make_dataset()

        data = PublicDatasetSerializer(dataset).data

        self.assertIsNone(data["bbox"])


class PublicDatasetListViewTests(TestCase):
    def test_returns_flat_list_of_active_public_datasets(self):
        make_dataset(name="visible-one", path="visible-one")
        make_dataset(name="hidden-inactive", path="hidden-inactive", active=False)
        make_dataset(name="hidden-private", path="hidden-private", public=False)

        response = self.client.get(reverse("public_api:dataset-list"))

        self.assertEqual(response.status_code, 200)
        names = {d["name"] for d in response.json()}
        self.assertEqual(names, {"visible-one"})


class PublicDatasetDetailViewTests(TestCase):
    def test_returns_dataset_by_name(self):
        make_dataset(name="lookup-me", path="lookup-me", title="Lookup Me")

        response = self.client.get(
            reverse("public_api:dataset-detail", kwargs={"name": "lookup-me"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "lookup-me")

    def test_missing_dataset_returns_public_envelope_404(self):
        response = self.client.get(
            reverse("public_api:dataset-detail", kwargs={"name": "does-not-exist"})
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
        self.assertIn("code", response.json()["error"])


class PublicDatasetCategoryViewTests(TestCase):
    def test_returns_deduplicated_tags(self):
        make_dataset(name="tagged-a", path="tagged-a", tags=["climate", "raster"])
        make_dataset(name="tagged-b", path="tagged-b", tags=["climate"])

        response = self.client.get(reverse("public_api:dataset-categories"))

        self.assertEqual(response.status_code, 200)
        tags = {c["tag"] for c in response.json()}
        self.assertEqual(tags, {"climate", "raster"})


class PublicDatasetCoverageViewTests(TestCase):
    def test_returns_datasets_covering_given_feature_ids(self):
        covered = make_dataset(name="covered", path="covered")
        uncovered = make_dataset(name="uncovered", path="uncovered")
        # Creating a Feature synchronously auto-inserts status=-1 (untested)
        # Coverage rows against every existing dataset (see
        # features.signals.on_feature_created), so the row for `covered`
        # already exists here — flip it to confirmed (status=1) rather than
        # creating it. `uncovered` is left at -1 (untested), which must not
        # count as "covering" the feature.
        feature = Feature.objects.create(shape="POINT(0 0)")
        Coverage.objects.filter(dataset=covered, geom_id=feature.id).update(status=1)

        response = self.client.post(
            reverse("public_api:dataset-coverage"),
            data={"featureIds": [feature.id]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        names = {d["name"] for d in response.json()}
        self.assertEqual(names, {"covered"})

    def test_malformed_body_returns_public_envelope_400(self):
        response = self.client.post(
            reverse("public_api:dataset-coverage"),
            data={"featureIds": "not-a-list"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class PublicApiSchemaCoversDatasetRoutesTests(TestCase):
    def test_dataset_paths_appear_in_schema(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")

        paths = response.json()["paths"]
        self.assertIn("/datasets/", paths)
        self.assertIn("/datasets/{name}/", paths)
        self.assertIn("/datasets/categories/", paths)
        self.assertIn("/datasets/coverage/", paths)
