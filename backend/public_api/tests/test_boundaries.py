from django.test import TestCase
from django.urls import reverse

from features.models import FeatureCollection
from public_api.serializers import PublicBoundarySerializer

EXPECTED_BOUNDARY_FIELDS = {
    "name",
    "title",
    "short_name",
    "description",
    "bbox",
    "group_name",
    "group_title",
    "group_level",
    "source_name",
    "tags",
}


def make_boundary(**overrides):
    defaults = dict(
        active=True,
        public=True,
        name="test-boundary",
        path="test-boundary",
        title="Test Boundary",
    )
    defaults.update(overrides)
    return FeatureCollection.objects.create(**defaults)


class PublicBoundarySerializerTests(TestCase):
    def test_field_stability(self):
        boundary = make_boundary()

        data = PublicBoundarySerializer(boundary).data

        self.assertEqual(set(data.keys()), EXPECTED_BOUNDARY_FIELDS)


class PublicBoundaryAutocompleteViewTests(TestCase):
    def test_filters_to_active_public_boundaries_matching_query(self):
        make_boundary(name="wm-districts", path="wm-districts", title="William & Mary Districts")
        make_boundary(name="hidden-inactive", path="hidden-inactive", active=False)

        response = self.client.get(reverse("public_api:boundary-autocomplete"), {"q": "William"})

        self.assertEqual(response.status_code, 200)
        names = {b["name"] for b in response.json()}
        self.assertEqual(names, {"wm-districts"})

    def test_invalid_limit_returns_public_envelope_400(self):
        response = self.client.get(reverse("public_api:boundary-autocomplete"), {"limit": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class PublicBoundaryPresetsViewTests(TestCase):
    def test_returns_presets_from_yaml_via_shared_loader(self):
        response = self.client.get(reverse("public_api:boundary-presets"))

        self.assertEqual(response.status_code, 200)
        presets = response.json()
        self.assertIsInstance(presets, list)
        if presets:
            self.assertIn("name", presets[0])
            self.assertIn("sort_order", presets[0])


class PublicApiSchemaCoversBoundaryRoutesTests(TestCase):
    def test_boundary_paths_appear_in_schema(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")

        paths = response.json()["paths"]
        self.assertIn("/boundaries/autocomplete/", paths)
        self.assertIn("/boundaries/presets/", paths)
