from django.test import TestCase
from django.urls import reverse

from features.models import FeatureCollection


def make_feature_collection(**overrides):
    defaults = dict(
        active=True,
        public=True,
        name="test-fc",
        path="test-fc",
        title="Test Feature Collection",
    )
    defaults.update(overrides)
    return FeatureCollection.objects.create(**defaults)


class SearchActivePublicTests(TestCase):
    def test_filters_to_active_and_public(self):
        active_public = make_feature_collection(name="active-public", path="active-public")
        make_feature_collection(name="inactive", path="inactive", active=False)
        make_feature_collection(name="private", path="private", public=False)

        results = list(FeatureCollection.search_active_public())

        self.assertEqual(results, [active_public])

    def test_filters_by_search_query_across_name_title_description(self):
        make_feature_collection(name="wm-districts", path="wm-districts", title="William & Mary Districts")
        make_feature_collection(
            name="other-fc",
            path="other-fc",
            title="Other",
            description="Mentions William somewhere",
        )
        make_feature_collection(name="unrelated", path="unrelated", title="Unrelated")

        results = FeatureCollection.search_active_public("William")

        self.assertEqual({fc.name for fc in results}, {"wm-districts", "other-fc"})

    def test_empty_query_returns_all_active_public_ordered_by_name(self):
        make_feature_collection(name="zzz", path="zzz")
        make_feature_collection(name="aaa", path="aaa")

        results = list(FeatureCollection.search_active_public())

        self.assertEqual([fc.name for fc in results], ["aaa", "zzz"])


class FeatureCollectionAutocompleteViewTests(TestCase):
    def test_response_shape_matches_expected_fields(self):
        make_feature_collection(name="test-fc", path="test-fc")

        response = self.client.get(reverse("features:feature-collection-autocomplete"), {"q": "test"})

        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertEqual(len(results), 1)
        expected_keys = {
            "id",
            "name",
            "title",
            "short_name",
            "description",
            "bbox",
            "group_name",
            "group_title",
            "group_class",
            "group_level",
            "source_name",
            "tags",
            "date_added",
        }
        self.assertEqual(set(results[0].keys()), expected_keys)
        self.assertEqual(results[0]["name"], "test-fc")

    def test_excludes_inactive_and_private_collections(self):
        make_feature_collection(name="visible", path="visible")
        make_feature_collection(name="inactive", path="inactive", active=False)
        make_feature_collection(name="private", path="private", public=False)

        response = self.client.get(reverse("features:feature-collection-autocomplete"))

        self.assertEqual(response.status_code, 200)
        names = {fc["name"] for fc in response.json()}
        self.assertEqual(names, {"visible"})

    def test_invalid_limit_returns_400(self):
        response = self.client.get(reverse("features:feature-collection-autocomplete"), {"limit": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
