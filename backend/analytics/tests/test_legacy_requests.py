import secrets
from datetime import datetime, timezone as dt_timezone

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from analytics.models import LegacyRequest
from analytics.services import legacy_request_links, legacy_requests_for_user

User = get_user_model()

OID = "58c9be24c15e00b8f9fadc1c"


def make_legacy(**overrides):
    """A valid LegacyRequest, overridable per test.

    The id defaults to a fresh ObjectId-shaped value so a test can create
    several rows without having to invent ids; pass `id=` when the test
    asserts on the value itself.
    """
    fields = {
        "id": secrets.token_hex(12),
        "contact": "alice@example.com",
        "custom_name": "Request 03-15-17 18:20",
        "submit_time": datetime(2017, 3, 15, 18, 20, tzinfo=dt_timezone.utc),
        "complete_time": datetime(2017, 3, 15, 20, 15, tzinfo=dt_timezone.utc),
        "boundary_title": "Tanzania ADM3 Boundary - GADM 2.8",
        "boundary_name": "tza_adm3_gadm28",
        "boundary_group": "tza_gadm28",
        "dataset_titles": ["World Bank Geocoded Aid Data v1.4.1", "Population (GPW V4)"],
        "dataset_count": 2,
        "data": {"release_data": [], "raster_data": []},
    }
    fields.update(overrides)
    return LegacyRequest.objects.create(**fields)


class LegacyRequestModelTests(TestCase):
    def test_creates_with_objectid_primary_key(self):
        obj = make_legacy(id=OID)
        obj.refresh_from_db()
        self.assertEqual(obj.pk, OID)
        self.assertEqual(obj.dataset_count, 2)

    def test_dataset_titles_round_trip(self):
        obj = make_legacy()
        obj.refresh_from_db()
        self.assertEqual(
            obj.dataset_titles,
            ["World Bank Geocoded Aid Data v1.4.1", "Population (GPW V4)"],
        )

    def test_user_is_nulled_when_user_deleted(self):
        user = User.objects.create_user(username="alice", email="alice@example.com")
        obj = make_legacy(user=user)
        user.delete()
        obj.refresh_from_db()
        self.assertIsNone(obj.user)

    def test_str_includes_name(self):
        self.assertIn("Request 03-15-17 18:20", str(make_legacy()))


class LegacyRequestLinksTests(TestCase):
    @override_settings(LEGACY_DOWNLOAD_BASE_URL="")
    def test_no_links_when_base_url_unset(self):
        self.assertEqual(legacy_request_links(make_legacy()), {})

    @override_settings(LEGACY_DOWNLOAD_BASE_URL="https://archive.example.com/legacy")
    def test_download_url_when_configured(self):
        self.assertEqual(
            legacy_request_links(make_legacy(id=OID)),
            {"download_url": f"https://archive.example.com/legacy/{OID}.zip"},
        )

    @override_settings(LEGACY_DOWNLOAD_BASE_URL="https://archive.example.com/legacy/")
    def test_trailing_slash_does_not_double(self):
        links = legacy_request_links(make_legacy(id=OID))
        self.assertEqual(
            links["download_url"], f"https://archive.example.com/legacy/{OID}.zip"
        )


class LegacyRequestsForUserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", email="alice@example.com")
        EmailAddress.objects.create(
            user=self.user, email="alice@example.com", verified=True, primary=True
        )

    def test_returns_fk_claimed_rows(self):
        obj = make_legacy(contact="someone-else@example.com", user=self.user)
        self.assertEqual(list(legacy_requests_for_user(self.user)), [obj])

    def test_returns_verified_email_matches_without_fk(self):
        obj = make_legacy(contact="Alice@Example.com")
        self.assertEqual(list(legacy_requests_for_user(self.user)), [obj])

    def test_ignores_unverified_email_matches(self):
        EmailAddress.objects.create(
            user=self.user, email="alias@example.com", verified=False
        )
        make_legacy(contact="alias@example.com")
        self.assertEqual(list(legacy_requests_for_user(self.user)), [])

    def test_never_returns_another_users_rows(self):
        bob = User.objects.create_user(username="bob", email="bob@example.com")
        EmailAddress.objects.create(user=bob, email="bob@example.com", verified=True)
        make_legacy(contact="bob@example.com")
        self.assertEqual(list(legacy_requests_for_user(self.user)), [])

    def test_orders_newest_first(self):
        older = make_legacy(
            contact="alice@example.com",
            submit_time=datetime(2017, 1, 1, tzinfo=dt_timezone.utc),
        )
        newer = make_legacy(
            contact="alice@example.com",
            submit_time=datetime(2020, 1, 1, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(list(legacy_requests_for_user(self.user)), [newer, older])
