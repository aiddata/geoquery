from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from analytics.models import LegacyRequest

User = get_user_model()

OID = "58c9be24c15e00b8f9fadc1c"


def make_legacy(**overrides):
    """A valid LegacyRequest, overridable per test."""
    fields = {
        "id": OID,
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
        obj = make_legacy()
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
