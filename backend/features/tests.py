from django.contrib.gis.geos import Point, Polygon
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from features.matviews import update_simplified_geometries
from features.models import FeatMap, Feature, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin


def make_feature_collection(**overrides):
    defaults = dict(
        active=True,
        public=True,
        name="test-fc",
        path="test-fc",
        title="Test Feature Collection",
    )
    defaults.update(overrides)
    return FeatureCollection.objects.create(**defaults)


class SearchActivePublicTests(TestCase):
    def test_filters_to_active_and_public(self):
        active_public = make_feature_collection(name="active-public", path="active-public")
        make_feature_collection(name="inactive", path="inactive", active=False)
        make_feature_collection(name="private", path="private", public=False)

        results = list(FeatureCollection.search_active_public())

        self.assertEqual(results, [active_public])

    def test_filters_by_search_query_across_name_title_description(self):
        make_feature_collection(name="wm-districts", path="wm-districts", title="William & Mary Districts")
        make_feature_collection(
            name="other-fc",
            path="other-fc",
            title="Other",
            description="Mentions William somewhere",
        )
        make_feature_collection(name="unrelated", path="unrelated", title="Unrelated")

        results = FeatureCollection.search_active_public("William")

        self.assertEqual({fc.name for fc in results}, {"wm-districts", "other-fc"})

    def test_empty_query_returns_all_active_public_ordered_by_name(self):
        make_feature_collection(name="zzz", path="zzz")
        make_feature_collection(name="aaa", path="aaa")

        results = list(FeatureCollection.search_active_public())

        self.assertEqual([fc.name for fc in results], ["aaa", "zzz"])


class FeatureCollectionAutocompleteViewTests(ReplicaReadsTestMixin, TestCase):
    def test_response_shape_matches_expected_fields(self):
        make_feature_collection(name="test-fc", path="test-fc")

        response = self.client.get(reverse("features:feature-collection-autocomplete"), {"q": "test"})

        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertEqual(len(results), 1)
        expected_keys = {
            "id",
            "name",
            "title",
            "short_name",
            "description",
            "bbox",
            "group_name",
            "group_title",
            "group_class",
            "group_level",
            "source_name",
            "source_url",
            "license",
            "license_url",
            "citation",
            "tags",
            "date_added",
        }
        self.assertEqual(set(results[0].keys()), expected_keys)
        self.assertEqual(results[0]["name"], "test-fc")

    def test_excludes_inactive_and_private_collections(self):
        make_feature_collection(name="visible", path="visible")
        make_feature_collection(name="inactive", path="inactive", active=False)
        make_feature_collection(name="private", path="private", public=False)

        response = self.client.get(reverse("features:feature-collection-autocomplete"))

        self.assertEqual(response.status_code, 200)
        names = {fc["name"] for fc in response.json()}
        self.assertEqual(names, {"visible"})

    def test_invalid_limit_returns_400(self):
        response = self.client.get(reverse("features:feature-collection-autocomplete"), {"limit": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class FeatureRepresentativePointTests(TestCase):
    square = Polygon(((0, 0), (0, 2), (2, 2), (2, 0), (0, 0)), srid=4326)
    shifted = Polygon(((10, 10), (10, 12), (12, 12), (12, 10), (10, 10)), srid=4326)

    def test_create_defaults_to_centroid(self):
        feature = Feature.objects.create(shape=self.square)
        feature.refresh_from_db()

        self.assertEqual(feature.representative_point, Point(1, 1, srid=4326))

    def test_create_from_wkt_string_defaults_to_centroid(self):
        feature = Feature.objects.create(shape="POINT(3 4)")
        feature.refresh_from_db()

        self.assertEqual(feature.representative_point, Point(3, 4, srid=4326))

    def test_explicit_value_is_kept(self):
        feature = Feature.objects.create(
            shape=self.square, representative_point=Point(0.5, 0.5, srid=4326)
        )
        feature.refresh_from_db()

        self.assertEqual(feature.representative_point, Point(0.5, 0.5, srid=4326))

    def test_bulk_create_defaults_to_centroid(self):
        Feature.objects.bulk_create([Feature(shape=self.square)])

        feature = Feature.objects.get()
        self.assertEqual(feature.representative_point, Point(1, 1, srid=4326))

    def test_save_after_shape_change_recomputes_point(self):
        feature = Feature.objects.create(shape=self.square)
        feature = Feature.objects.get(pk=feature.pk)

        feature.shape = self.shifted
        feature.save()

        self.assertEqual(feature.representative_point, Point(11, 11, srid=4326))
        feature.refresh_from_db()
        self.assertEqual(feature.representative_point, Point(11, 11, srid=4326))

    def test_save_after_shape_change_keeps_point_set_in_same_write(self):
        feature = Feature.objects.create(shape=self.square)
        feature = Feature.objects.get(pk=feature.pk)

        feature.shape = self.shifted
        feature.representative_point = Point(10.5, 10.5, srid=4326)
        feature.save()

        feature.refresh_from_db()
        self.assertEqual(feature.representative_point, Point(10.5, 10.5, srid=4326))

    def test_queryset_update_of_shape_recomputes_point(self):
        feature = Feature.objects.create(shape=self.square)

        Feature.objects.filter(pk=feature.pk).update(shape=self.shifted)

        feature.refresh_from_db()
        self.assertEqual(feature.representative_point, Point(11, 11, srid=4326))

    def test_queryset_update_with_explicit_point_keeps_it(self):
        feature = Feature.objects.create(shape=self.square)

        Feature.objects.filter(pk=feature.pk).update(
            shape=self.shifted, representative_point=Point(10.5, 10.5, srid=4326)
        )

        feature.refresh_from_db()
        self.assertEqual(feature.representative_point, Point(10.5, 10.5, srid=4326))

    def test_raw_sql_insert_defaults_to_centroid(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO features (shape) VALUES (ST_GeomFromText(%s, 4326)) RETURNING id",
                [self.square.wkt],
            )
            (feature_id,) = cursor.fetchone()

        feature = Feature.objects.get(pk=feature_id)
        self.assertEqual(feature.representative_point, Point(1, 1, srid=4326))


class PointTileTests(ReplicaReadsTestMixin, TestCase):
    """Tiles at or below FEATURE_TILE_POINT_MAX_ZOOM carry representative points.

    The feature's polygon lies in the north-east quadrant, but its point is in
    the south-west one. Whether a tile is empty therefore shows which geometry
    it was built from, without needing an MVT decoder.
    """

    polygon = Polygon(((10, 10), (10, 60), (170, 60), (170, 10), (10, 10)), srid=4326)
    point = Point(-100, -40, srid=4326)

    # z/x/y of tiles containing the polygon but not the point, and vice versa.
    POLYGON_TILE_Z1 = (1, 1, 0)
    POINT_TILE_Z1 = (1, 0, 1)
    POLYGON_TILE_Z2 = (2, 2, 1)

    def setUp(self):
        self.fc = make_feature_collection(name="tile-fc", path="tile-fc")
        self.upload_fc = make_feature_collection(
            name="user_upload_tiles", path="user_upload_tiles", is_user_upload=True
        )
        for fc in (self.fc, self.upload_fc):
            feature = Feature.objects.create(
                shape=self.polygon, representative_point=self.point
            )
            FeatMap.objects.create(fc=fc, geom=feature, name="Somewhere")
        update_simplified_geometries(self.fc.id)

    def get_tile(self, fc, z, x, y):
        response = self.client.get(
            reverse("features:feature-collection-tiles", args=[fc.name, z, x, y])
        )
        self.assertEqual(response.status_code, 200)
        return response.content

    def test_disabled_by_default_serves_polygons(self):
        self.assertNotEqual(self.get_tile(self.fc, *self.POLYGON_TILE_Z1), b"")
        self.assertEqual(self.get_tile(self.fc, *self.POINT_TILE_Z1), b"")

    @override_settings(FEATURE_TILE_POINT_MAX_ZOOM=1)
    def test_serves_points_at_or_below_threshold(self):
        for fc in (self.fc, self.upload_fc):
            with self.subTest(fc=fc.name):
                self.assertEqual(self.get_tile(fc, *self.POLYGON_TILE_Z1), b"")
                self.assertNotEqual(self.get_tile(fc, *self.POINT_TILE_Z1), b"")

    @override_settings(FEATURE_TILE_POINT_MAX_ZOOM=1)
    def test_serves_polygons_above_threshold(self):
        for fc in (self.fc, self.upload_fc):
            with self.subTest(fc=fc.name):
                self.assertNotEqual(self.get_tile(fc, *self.POLYGON_TILE_Z2), b"")

    @override_settings(FEATURE_TILE_POINT_MAX_ZOOM=2)
    def test_threshold_is_inclusive(self):
        self.assertEqual(self.get_tile(self.fc, *self.POLYGON_TILE_Z2), b"")
