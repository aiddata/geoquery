from unittest.mock import patch

from django.test import RequestFactory, TestCase
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from public_api.authentication import PublicApiConsumer, PublicApiKeyAuthentication, resolve_api_key
from public_api.exceptions import public_api_exception_handler
from public_api.throttling import PublicApiThrottle


class PublicApiKeyAuthenticationTests(TestCase):
    def setUp(self):
        self.auth = PublicApiKeyAuthentication()
        self.factory = RequestFactory()

    def test_resolve_api_key_is_stubbed_to_always_return_none(self):
        self.assertIsNone(resolve_api_key("any-key-at-all"))

    def test_authenticate_returns_none_without_authorization_header(self):
        request = self.factory.get("/api/public/v1/datasets/")
        self.assertIsNone(self.auth.authenticate(request))

    def test_authenticate_returns_none_with_a_wellformed_key_header(self):
        request = self.factory.get(
            "/api/public/v1/datasets/", HTTP_AUTHORIZATION="Api-Key some-key-value"
        )
        self.assertIsNone(self.auth.authenticate(request))

    def test_authenticate_returns_none_with_empty_key_after_prefix(self):
        request = self.factory.get(
            "/api/public/v1/datasets/", HTTP_AUTHORIZATION="Api-Key "
        )
        self.assertIsNone(self.auth.authenticate(request))


class PublicApiThrottleTests(TestCase):
    def setUp(self):
        self.throttle = PublicApiThrottle()
        self.factory = APIRequestFactory()

    def test_cache_key_falls_back_to_ip_when_no_consumer_resolved(self):
        django_request = self.factory.get("/api/public/v1/datasets/", REMOTE_ADDR="203.0.113.5")
        request = Request(django_request)

        key = self.throttle.get_cache_key(request, view=APIView())

        self.assertIn("public_api_anon", key)
        self.assertEqual(self.throttle.scope, "public_api_anon")

    def test_cache_key_uses_consumer_tier_when_its_rate_is_configured(self):
        self.throttle.THROTTLE_RATES = {"public_api_anon": "100/hour", "premium": "500/hour"}
        django_request = self.factory.get("/api/public/v1/datasets/")
        request = Request(django_request)
        request._user = PublicApiConsumer(id=42, rate_limit_tier="premium", is_active=True)

        key = self.throttle.get_cache_key(request, view=APIView())

        self.assertIn("consumer:42", key)
        self.assertEqual(self.throttle.scope, "premium")

    def test_cache_key_falls_back_to_anon_scope_when_tier_rate_is_unconfigured(self):
        django_request = self.factory.get("/api/public/v1/datasets/")
        request = Request(django_request)
        request._user = PublicApiConsumer(id=42, rate_limit_tier="unconfigured-tier", is_active=True)

        key = self.throttle.get_cache_key(request, view=APIView())

        self.assertIn("consumer:42", key)
        self.assertEqual(self.throttle.scope, "public_api_anon")

    def test_authentication_and_throttle_integrate_via_request_user(self):
        # Exercises the real seam end-to-end: PublicApiKeyAuthentication
        # populates request.user/request.auth via DRF's lazy
        # authenticator machinery, and PublicApiThrottle reads
        # request.user off of that — rather than each half being poked
        # independently via _user/_auth.
        django_request = self.factory.get(
            "/api/public/v1/datasets/", HTTP_AUTHORIZATION="Api-Key some-key-value"
        )
        request = Request(django_request, authenticators=[PublicApiKeyAuthentication()])

        consumer = PublicApiConsumer(id=7, rate_limit_tier="public_api_anon", is_active=True)
        with patch("public_api.authentication.resolve_api_key", return_value=consumer):
            key = self.throttle.get_cache_key(request, view=APIView())

        self.assertIn("consumer:7", key)


class PublicApiExceptionHandlerTests(TestCase):
    def test_wraps_drf_error_in_public_envelope(self):
        response = public_api_exception_handler(NotFound("no such dataset"), context={})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.data,
            {"error": {"code": 404, "message": "no such dataset"}},
        )

    def test_wraps_multifield_validation_error_without_unwrapping_detail(self):
        response = public_api_exception_handler(
            ValidationError({"email": ["This field is required."]}), context={}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], 400)
        self.assertEqual(
            response.data["error"]["message"],
            {"email": ["This field is required."]},
        )
