from datetime import datetime, timedelta, timezone as dt_timezone

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from analytics.models import LegacyRequest, RequestToken

User = get_user_model()


def make_legacy(oid, contact="alice@example.com", **overrides):
    fields = {
        "id": oid,
        "contact": contact,
        "custom_name": "Request 03-15-17 18:20",
        "submit_time": datetime(2017, 3, 15, 18, 20, tzinfo=dt_timezone.utc),
        "complete_time": datetime(2017, 3, 15, 19, 20, tzinfo=dt_timezone.utc),
        "boundary_title": "Tanzania ADM3 Boundary - GADM 2.8",
        "boundary_name": "tza_adm3_gadm28",
        "boundary_group": "tza_gadm28",
        "dataset_titles": ["World Bank Geocoded Aid Data v1.4.1"],
        "dataset_count": 1,
        "data": {"release_data": [], "raster_data": []},
    }
    fields.update(overrides)
    return LegacyRequest.objects.create(**fields)


class LegacyMyRequestsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="alice", email="alice@example.com", password="pw"
        )
        EmailAddress.objects.create(
            user=self.user, email="alice@example.com", verified=True, primary=True
        )

    def test_requires_authentication(self):
        self.assertIn(
            self.client.get("/api/analytics/legacy-requests/").status_code, (401, 403)
        )

    def test_returns_own_rows_only(self):
        make_legacy("a" * 24)
        make_legacy("b" * 24, contact="bob@example.com")
        self.client.force_login(self.user)

        body = self.client.get("/api/analytics/legacy-requests/").json()

        self.assertEqual([r["id"] for r in body], ["a" * 24])
        self.assertTrue(body[0]["is_legacy"])
        self.assertEqual(body[0]["status_label"], "completed")
        self.assertEqual(body[0]["dataset_count"], 1)


class LegacyHistoryTests(TestCase):
    def test_returns_rows_for_token_email(self):
        make_legacy("a" * 24)
        make_legacy("b" * 24, contact="bob@example.com")
        _, raw = RequestToken.create_for_email(
            "alice@example.com", timezone.now() + timedelta(days=1)
        )

        body = self.client.get(f"/api/analytics/legacy-history/{raw}/").json()

        self.assertEqual([r["id"] for r in body], ["a" * 24])

    def test_unknown_token_is_404(self):
        response = self.client.get("/api/analytics/legacy-history/nope/")

        self.assertEqual(response.status_code, 404)
        # Assert the 404 came from the view, not from the URL resolver: a
        # missing route also returns 404, so a bare status check would pass
        # even with the endpoint deleted.
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"error": "Invalid or expired link."})

    def test_expired_token_is_410(self):
        _, raw = RequestToken.create_for_email(
            "alice@example.com", timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(
            self.client.get(f"/api/analytics/legacy-history/{raw}/").status_code, 410
        )


class LegacyDetailTests(TestCase):
    def test_returns_detail(self):
        make_legacy("a" * 24)

        body = self.client.get(f"/api/analytics/legacy-requests/{'a' * 24}/").json()

        self.assertEqual(body["name"], "Request 03-15-17 18:20")
        self.assertEqual(body["boundary_title"], "Tanzania ADM3 Boundary - GADM 2.8")
        self.assertEqual(
            body["dataset_titles"], ["World Bank Geocoded Aid Data v1.4.1"]
        )
        self.assertTrue(body["is_legacy"])

    def test_unknown_id_is_404(self):
        # Hex, so the route still matches and the VIEW answers -- a non-hex id
        # is now rejected by the resolver, which would not exercise the view.
        response = self.client.get(f"/api/analytics/legacy-requests/{'f' * 24}/")

        self.assertEqual(response.status_code, 404)
        # As above: proves the view answered, not the resolver.
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"error": "Not found"})

    @override_settings(LEGACY_DOWNLOAD_BASE_URL="")
    def test_no_download_url_when_unconfigured(self):
        make_legacy("a" * 24)
        body = self.client.get(f"/api/analytics/legacy-requests/{'a' * 24}/").json()
        # Positive anchor first: asserting only the absence of a key would
        # pass against a view stubbed to return {}.
        self.assertEqual(body["id"], "a" * 24)
        self.assertNotIn("download_url", body)

    @override_settings(LEGACY_DOWNLOAD_BASE_URL="https://archive.example.com")
    def test_download_url_when_configured(self):
        make_legacy("a" * 24)
        body = self.client.get(f"/api/analytics/legacy-requests/{'a' * 24}/").json()
        self.assertEqual(
            body["download_url"],
            f"https://archive.example.com/legacy/{'a' * 24}.zip",
        )

    def test_detail_never_exposes_submitter_or_raw_data(self):
        """The payload is enumerated, not filtered -- keep it that way.

        This endpoint is AllowAny, and the model carries the submitter's email
        in ``contact``, the full release/raster JSON in ``data``, and the
        owning account in ``user``. Nothing currently fails if someone adds one
        of those to the payload while building the frontend, so this does.
        """
        make_legacy("a" * 24)

        body = self.client.get(f"/api/analytics/legacy-requests/{'a' * 24}/").json()

        self.assertEqual(body["id"], "a" * 24)
        for leaked in ("contact", "data", "user"):
            self.assertNotIn(leaked, body)
