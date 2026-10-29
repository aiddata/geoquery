from django.contrib.gis.geos import Point, Polygon
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from features.models import Feature, FeatureCollection
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


class MultiCollectionTileTests(ReplicaReadsTestMixin, TestCase):
    # Tile geometry is read through the "replica" alias.

    @staticmethod
    def _square(x, y):
        return Polygon(((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1), (x, y)), srid=4326)

    def setUp(self):
        from features.matviews import update_simplified_geometries
        from features.models import FeatMap

        self.fcs = []
        # Both squares sit inside z2 tile 2/1/1 (lon 0..90, lat 0..66.5).
        for name, x in (("fc-west", 1.0), ("fc-east", 10.0)):
            fc = make_feature_collection(name=name, path=name)
            feature = Feature.objects.create(shape=self._square(x, 1.0))
            FeatMap.objects.create(fc=fc, geom=feature, name=f"{name} unit")
            update_simplified_geometries(fc.id)
            self.fcs.append(fc)

    def _get(self, zxy, ids):
        return self.client.get(
            f"/api/features/multitiles/{zxy}.mvt?fc={','.join(str(i) for i in ids)}"
        )

    def test_tile_holds_every_selected_collection_in_one_layer(self):
        response = self._get("2/2/1", [fc.id for fc in self.fcs])
        self.assertEqual(response.status_code, 200)
        body = response.content
        # MVT stores layer names, keys and string values verbatim.
        self.assertIn(b"boundaries", body)
        self.assertIn(b"fc_id", body)
        self.assertIn(b"fc-west unit", body)
        self.assertIn(b"fc-east unit", body)

    def test_unselected_collections_are_left_out(self):
        body = self._get("2/2/1", [self.fcs[0].id]).content
        self.assertIn(b"fc-west unit", body)
        self.assertNotIn(b"fc-east unit", body)

    def test_tile_away_from_the_features_is_empty(self):
        response = self._get("2/0/0", [fc.id for fc in self.fcs])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    def test_per_collection_endpoint_keeps_its_layer_name(self):
        body = self.client.get("/api/features/tiles/fc-west/2/2/1.mvt").content
        self.assertIn(b"fc-west", body)
        self.assertNotIn(b"boundaries", body)

    def test_simplified_tables_have_composite_fc_shape_index(self):
        tables = [
            "features_simplified_z0_5",
            "features_simplified_z6_9",
            "features_simplified_z10_12",
        ]
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_indexes"
                " WHERE indexname = tablename || '_fc_id_shape_idx'"
                " AND indexdef ILIKE '%%USING gist (fc_id, shape)%%'"
            )
            self.assertEqual(sorted(r[0] for r in cursor.fetchall()), sorted(tables))
