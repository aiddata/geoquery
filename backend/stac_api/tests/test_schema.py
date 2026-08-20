from django.test import TestCase
from django.urls import reverse

EXPECTED_PATHS = {
    "/",
    "/conformance/",
    "/search/",
    "/collections/",
    "/collections/{name}/",
    "/collections/{name}/items/",
    "/collections/{name}/items/{item_id}/",
}


class StacApiSchemaTests(TestCase):
    def setUp(self):
        response = self.client.get(reverse("stac_api:schema"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.schema = response.json()

    def test_schema_has_stac_specific_title(self):
        self.assertEqual(self.schema["info"]["title"], "GeoQuery STAC API")

    def test_schema_covers_exactly_the_stac_routes(self):
        self.assertEqual(set(self.schema["paths"].keys()), EXPECTED_PATHS)

    def test_no_public_api_or_internal_paths_leak_in(self):
        for path in self.schema["paths"]:
            self.assertNotIn("datasets", path)
            self.assertNotIn("boundaries", path)


class StacApiDocsViewTests(TestCase):
    def test_docs_page_renders(self):
        response = self.client.get(reverse("stac_api:docs"))
        self.assertEqual(response.status_code, 200)
