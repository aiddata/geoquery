from django.test import TestCase
from django.urls import reverse

EXPECTED_PATHS = {
    "/datasets/",
    "/datasets/categories/",
    "/datasets/coverage/",
    "/datasets/{name}/",
    "/boundaries/autocomplete/",
    "/boundaries/presets/",
    "/boundaries/{name}/",
}

# These views override .list() to return a bare flat array (matching the
# internal API's "flat list, no pagination wrapper" convention) but are
# ListAPIView subclasses, so without pagination_class = None,
# drf-spectacular documents them as paginated even though they never are.
FLAT_LIST_PATHS = {
    "/datasets/",
    "/datasets/categories/",
    "/boundaries/autocomplete/",
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

    def test_flat_list_endpoints_are_not_documented_as_paginated(self):
        # These views manually return Response(serializer.data) — a bare
        # array — from an overridden .list(), never a {count, next,
        # previous, results} envelope. The schema must say so too.
        for path in FLAT_LIST_PATHS:
            get = self.schema["paths"][path]["get"]
            response_schema = get["responses"]["200"]["content"]["application/json"]["schema"]
            self.assertEqual(
                response_schema.get("type"),
                "array",
                f"GET {path} response schema should be a plain array, got {response_schema}",
            )

            param_names = {param.get("name") for param in get.get("parameters", [])}
            self.assertNotIn(
                "page",
                param_names,
                f"GET {path} should not document a 'page' query param — it is never paginated",
            )
