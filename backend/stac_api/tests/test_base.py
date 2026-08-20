from django.test import TestCase
from django.urls import reverse


class StacApiCorsTests(TestCase):
    def test_get_response_carries_wildcard_cors_header(self):
        response = self.client.get(reverse("stac_api:landing-page"))
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_options_preflight_carries_cors_headers(self):
        response = self.client.options(reverse("stac_api:landing-page"))
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("GET", response["Access-Control-Allow-Methods"])
