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

    def test_no_trailing_slash_serves_directly_without_a_redirect(self):
        # Django's APPEND_SLASH would otherwise 301-redirect "/api/stac/v1"
        # to "/api/stac/v1/" via CommonMiddleware, before the view (and
        # StacApiBaseMixin.finalize_response) ever runs — so the redirect
        # response carries no CORS headers. A browser treats a redirected
        # preflight as a failed one, breaking any STAC client pointed at
        # the catalog root without a trailing slash (the natural way to
        # hand a client a "catalog URL"). Confirmed live against prod.
        response = self.client.get("/api/stac/v1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "Catalog")

    def test_no_trailing_slash_preflight_carries_cors_headers(self):
        response = self.client.options(
            "/api/stac/v1",
            HTTP_ORIGIN="https://stacindex.org",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")


class StacConformanceViewTests(TestCase):
    def test_returns_conformance_classes(self):
        response = self.client.get(reverse("stac_api:conformance"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "https://api.stacspec.org/v1.0.0/core", response.json()["conformsTo"]
        )
