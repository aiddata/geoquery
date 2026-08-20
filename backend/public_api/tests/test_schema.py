from django.test import TestCase
from django.urls import reverse

EXPECTED_PATHS = {
    "/datasets/",
    "/datasets/categories/",
    "/datasets/coverage/",
    "/datasets/{name}/",
    "/boundaries/autocomplete/",
    "/boundaries/presets/",
}


class PublicApiFullSchemaTests(TestCase):
    def setUp(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.schema = response.json()

    def test_schema_document_metadata_is_present(self):
        self.assertEqual(self.schema["openapi"][0], "3")
        self.assertEqual(self.schema["info"]["title"], "GeoQuery Public API")
        self.assertTrue(self.schema["info"]["version"])

    def test_schema_covers_exactly_the_v1_public_routes(self):
        self.assertEqual(set(self.schema["paths"].keys()), EXPECTED_PATHS)

    def test_every_path_documents_at_least_one_response(self):
        for path, operations in self.schema["paths"].items():
            for method, operation in operations.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                self.assertTrue(
                    operation.get("responses"),
                    f"{method.upper()} {path} has no documented responses",
                )
