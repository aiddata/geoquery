"""The dataset category menu: settings.DATASET_CATEGORIES applied to tags."""

from django.test import TestCase, override_settings

from datasets.models import Dataset
from geoquery.testing import ReplicaReadsTestMixin

CATEGORIES = {
    "Climate & Weather": ["temperature", "precipitation"],
    "Health": ["health", "population"],
    "Population": ["population"],
    "Energy": ["solar"],  # no dataset has this: left out of the menu
}


@override_settings(DATASET_CATEGORIES=CATEGORIES)
class DatasetCategoryViewTests(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        for name, tags in (("cru", ["CRU", "Temperature"]), ("gpw", ["population"]), ("hidden", ["health"])):
            Dataset.objects.create(
                name=name, path=f"/d/{name}", active=True, public=name != "hidden", tags=tags
            )

    def get(self):
        response = self.client.get("/api/datasets/categories/")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_categories_follow_the_setting_in_order(self):
        self.assertEqual(
            self.get(),
            [
                {"tag": "climate_weather", "display": "Climate & Weather", "tags": ["temperature", "precipitation"]},
                {"tag": "health", "display": "Health", "tags": ["health", "population"]},
                {"tag": "population", "display": "Population", "tags": ["population"]},
            ],
        )

    def test_tags_match_regardless_of_case(self):
        # "Temperature" on the dataset matches "temperature" in the setting
        self.assertIn("Climate & Weather", [c["display"] for c in self.get()])

    def test_categories_only_reachable_through_hidden_datasets_are_left_out(self):
        Dataset.objects.filter(name="gpw").update(public=False)
        self.assertNotIn("Health", [c["display"] for c in self.get()])
