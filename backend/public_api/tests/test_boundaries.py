from django.test import TestCase
from django.urls import reverse

from features.models import Feature, FeatMap, FeatureCollection
from public_api.serializers import PublicBoundaryDetailSerializer, PublicBoundarySerializer

EXPECTED_BOUNDARY_FIELDS = {
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
}

EXPECTED_BOUNDARY_DETAIL_FIELDS = EXPECTED_BOUNDARY_FIELDS | {"feature_ids"}


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


def make_feature():
    return Feature.objects.create(shape="POINT(0 0)")


class PublicBoundarySerializerTests(TestCase):
    def test_field_stability(self):
        boundary = make_boundary()

        data = PublicBoundarySerializer(boundary).data

        self.assertEqual(set(data.keys()), EXPECTED_BOUNDARY_FIELDS)


class PublicBoundaryDetailSerializerTests(TestCase):
    def test_field_stability(self):
        boundary = make_boundary()

        data = PublicBoundaryDetailSerializer(boundary).data

        self.assertEqual(set(data.keys()), EXPECTED_BOUNDARY_DETAIL_FIELDS)

    def test_feature_ids_resolves_via_featmap_for_this_boundary_only(self):
        boundary = make_boundary()
        other_boundary = make_boundary(name="other-boundary", path="other-boundary")
        feature_one = make_feature()
        feature_two = make_feature()
        other_feature = make_feature()
        FeatMap.objects.create(fc=boundary, geom=feature_one)
        FeatMap.objects.create(fc=boundary, geom=feature_two)
        FeatMap.objects.create(fc=other_boundary, geom=other_feature)

        data = PublicBoundaryDetailSerializer(boundary).data

        self.assertEqual(set(data["feature_ids"]), {feature_one.id, feature_two.id})


class PublicBoundaryAutocompleteViewTests(TestCase):
    def test_filters_to_active_public_boundaries_matching_query(self):
        make_boundary(name="wm-districts", path="wm-districts", title="William & Mary Districts")
        make_boundary(name="hidden-inactive", path="hidden-inactive", active=False)

        response = self.client.get(reverse("public_api:boundary-autocomplete"), {"q": "William"})

        self.assertEqual(response.status_code, 200)
        names = {b["name"] for b in response.json()}
        self.assertEqual(names, {"wm-districts"})

    def test_excludes_private_boundaries_even_when_active(self):
        make_boundary(name="wm-districts", path="wm-districts", title="William & Mary Districts")
        make_boundary(
            name="hidden-private",
            path="hidden-private",
            title="William & Mary Private",
            public=False,
        )

        response = self.client.get(reverse("public_api:boundary-autocomplete"), {"q": "William"})

        self.assertEqual(response.status_code, 200)
        names = {b["name"] for b in response.json()}
        self.assertEqual(names, {"wm-districts"})

    def test_invalid_limit_returns_public_envelope_400(self):
        response = self.client.get(reverse("public_api:boundary-autocomplete"), {"limit": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class PublicBoundaryDetailViewTests(TestCase):
    def test_returns_boundary_by_name_with_feature_ids(self):
        boundary = make_boundary(name="lookup-me", path="lookup-me", title="Lookup Me")
        feature = make_feature()
        FeatMap.objects.create(fc=boundary, geom=feature)

        response = self.client.get(
            reverse("public_api:boundary-detail", kwargs={"name": "lookup-me"})
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "lookup-me")
        self.assertEqual(body["feature_ids"], [feature.id])

    def test_missing_boundary_returns_public_envelope_404(self):
        response = self.client.get(
            reverse("public_api:boundary-detail", kwargs={"name": "does-not-exist"})
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
        self.assertIn("code", response.json()["error"])

    def test_inactive_boundary_returns_404(self):
        make_boundary(name="hidden-inactive", path="hidden-inactive", active=False)

        response = self.client.get(
            reverse("public_api:boundary-detail", kwargs={"name": "hidden-inactive"})
        )

        self.assertEqual(response.status_code, 404)

    def test_private_boundary_returns_404(self):
        make_boundary(name="hidden-private", path="hidden-private", public=False)

        response = self.client.get(
            reverse("public_api:boundary-detail", kwargs={"name": "hidden-private"})
        )

        self.assertEqual(response.status_code, 404)


class PublicBoundaryPresetsViewTests(TestCase):
    def test_returns_presets_from_yaml_via_shared_loader(self):
        response = self.client.get(reverse("public_api:boundary-presets"))

        self.assertEqual(response.status_code, 200)
        presets = response.json()
        self.assertIsInstance(presets, list)
        self.assertGreater(len(presets), 0)
        self.assertIn("name", presets[0])
        self.assertIn("sort_order", presets[0])


class PublicApiSchemaCoversBoundaryRoutesTests(TestCase):
    def test_boundary_paths_appear_in_schema(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")

        paths = response.json()["paths"]
        self.assertIn("/boundaries/autocomplete/", paths)
        self.assertIn("/boundaries/presets/", paths)
        self.assertIn("/boundaries/{name}/", paths)
