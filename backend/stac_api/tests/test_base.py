from django.test import TestCase
from django.urls import reverse


class StacApiCorsTests(TestCase):
    def test_get_response_carries_wildcard_cors_header(self):
        response = self.client.get(reverse("stac_api:landing-page"))
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_options_preflight_carries_cors_headers(self):
        # Simulate a real browser preflight: an Origin not in
        # CORS_ALLOWED_ORIGINS plus Access-Control-Request-Method. Without
        # CORS_URLS_REGEX excluding /api/stac/, corsheaders' middleware
        # would intercept this and return its own response before the
        # view (and StacApiBaseMixin.finalize_response) ever runs, and
        # since the origin isn't allowlisted, no CORS header would be set
        # at all.
        response = self.client.options(
            reverse("stac_api:landing-page"),
            HTTP_ORIGIN="https://stacindex.org",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("GET", response["Access-Control-Allow-Methods"])

    def test_post_is_not_blocked_by_default_permission(self):
        # stac_api views override DRF's global IsAuthenticatedOrReadOnly
        # default (see StacApiBaseMixin). A POST to a view with no post()
        # handler should reach the view and fail with 405 Method Not
        # Allowed, not be rejected earlier with 401/403.
        response = self.client.post(reverse("stac_api:landing-page"))
        self.assertEqual(response.status_code, 405)
