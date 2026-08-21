from django.test import TestCase
from django.urls import reverse


class StacLandingPageViewTests(TestCase):
    def test_returns_stac_catalog_type(self):
        response = self.client.get(reverse("stac_api:landing-page"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "Catalog")
        self.assertEqual(data["stac_version"], "1.0.0")

    def test_links_include_self_root_conformance_data_search(self):
        response = self.client.get(reverse("stac_api:landing-page"))

        rels = {link["rel"] for link in response.json()["links"]}
        self.assertTrue(
            {"self", "root", "conformance", "data", "search", "service-doc"}.issubset(rels)
        )


class StacConformanceViewTests(TestCase):
    def test_returns_conformance_classes(self):
        response = self.client.get(reverse("stac_api:conformance"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "https://api.stacspec.org/v1.0.0/core", response.json()["conformsTo"]
        )
