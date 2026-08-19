from django.test import TestCase
from django.urls import reverse


class PublicApiScaffoldTests(TestCase):
    def test_schema_endpoint_returns_valid_openapi_document(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("openapi", data)
        self.assertIn("info", data)
        self.assertIsInstance(data["paths"], dict)

    def test_docs_endpoint_returns_swagger_ui(self):
        response = self.client.get(reverse("public_api:docs"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"swagger", response.content.lower())
