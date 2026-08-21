import datetime

from django.contrib.gis.geos import Polygon
from django.test import TestCase

from stac_api.utils import bbox_from_geometry, geojson_from_geometry, to_rfc3339


class BboxFromGeometryTests(TestCase):
    def test_returns_none_for_none_geometry(self):
        self.assertIsNone(bbox_from_geometry(None))

    def test_returns_extent_as_a_list(self):
        geom = Polygon.from_bbox((1, 2, 3, 4))
        self.assertEqual(bbox_from_geometry(geom), [1.0, 2.0, 3.0, 4.0])


class GeojsonFromGeometryTests(TestCase):
    def test_returns_none_for_none_geometry(self):
        self.assertIsNone(geojson_from_geometry(None))

    def test_returns_a_geojson_dict(self):
        geom = Polygon.from_bbox((1, 2, 3, 4))
        result = geojson_from_geometry(geom)
        self.assertEqual(result["type"], "Polygon")


class ToRfc3339Tests(TestCase):
    def test_returns_none_for_none(self):
        self.assertIsNone(to_rfc3339(None))

    def test_formats_aware_utc_datetime(self):
        dt = datetime.datetime(2020, 1, 1, 12, 30, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(to_rfc3339(dt), "2020-01-01T12:30:00Z")

    def test_converts_a_non_utc_aware_datetime(self):
        tz = datetime.timezone(datetime.timedelta(hours=-5))
        dt = datetime.datetime(2020, 1, 1, 7, 30, 0, tzinfo=tz)
        self.assertEqual(to_rfc3339(dt), "2020-01-01T12:30:00Z")

    def test_treats_a_naive_datetime_as_utc(self):
        dt = datetime.datetime(2020, 1, 1, 12, 30, 0)
        self.assertEqual(to_rfc3339(dt), "2020-01-01T12:30:00Z")
