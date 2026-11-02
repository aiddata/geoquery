import struct
from unittest import mock

from django.contrib.gis.geos import GEOSGeometry, Polygon
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


def _varint(buf, i):
    value = shift = 0
    while True:
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return value, i


def _fields(buf):
    """(field number, wire type, value) for each field of a protobuf message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 2:
            length, i = _varint(buf, i)
            value, i = buf[i : i + length], i + length
        elif wire == 1:
            value, i = buf[i : i + 8], i + 8
        elif wire == 5:
            value, i = buf[i : i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield field, wire, value


def _decode_value(buf):
    """An MVT Value message: string, float, double, int, uint, sint or bool."""
    ((field, _, value),) = _fields(buf)
    if field == 1:
        return value.decode()
    if field == 2:
        return struct.unpack("<f", value)[0]
    if field == 3:
        return struct.unpack("<d", value)[0]
    if field == 4:
        return value - (1 << 64) if value >= 1 << 63 else value
    if field == 6:
        return (value >> 1) ^ -(value & 1)
    if field == 7:
        return bool(value)
    return value


def decode_mvt_properties(body):
    """{layer name: [properties of each feature]} from an MVT tile.

    Geometry is skipped.
    """
    layers = {}
    for field, _, layer in _fields(bytes(body)):
        if field != 3:
            continue
        name, keys, values, features = None, [], [], []
        for f, _, v in _fields(layer):
            if f == 1:
                name = v.decode()
            elif f == 2:
                features.append(v)
            elif f == 3:
                keys.append(v.decode())
            elif f == 4:
                values.append(_decode_value(v))
        decoded = []
        for feature in features:
            tags = []
            for f, wire, v in _fields(feature):
                if f == 2:
                    j = 0
                    while j < len(v):
                        t, j = _varint(v, j)
                        tags.append(t)
            decoded.append({keys[k]: values[t] for k, t in zip(tags[::2], tags[1::2])})
        layers[name] = decoded
    return layers


class FeaturePointsTests(TestCase):
    square = Polygon(((0, 0), (0, 2), (2, 2), (2, 0), (0, 0)), srid=4326)

    def _points(self, fc_id):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT fm_id, geom_id, ST_SRID(pt), ST_AsText(ST_Transform(pt, 4326))"
                " FROM features_points WHERE fc_id = %s",
                [fc_id],
            )
            return cursor.fetchall()

    def test_update_writes_a_3857_centroid_per_feature(self):
        from features.matviews import update_simplified_geometries
        from features.models import FeatMap

        fc = make_feature_collection()
        feature = Feature.objects.create(shape=self.square)
        fm = FeatMap.objects.create(fc=fc, geom=feature, name="unit")

        update_simplified_geometries(fc.id)

        [(fm_id, geom_id, srid, wkt)] = self._points(fc.id)
        self.assertEqual((fm_id, geom_id, srid), (fm.id, feature.id, 3857))
        point = GEOSGeometry(wkt)
        self.assertAlmostEqual(point.x, 1, places=6)
        self.assertAlmostEqual(point.y, 1, places=6)

    def test_update_replaces_and_remove_deletes(self):
        from features.matviews import remove_simplified_geometries, update_simplified_geometries
        from features.models import FeatMap

        fc = make_feature_collection()
        feature = Feature.objects.create(shape=self.square)
        FeatMap.objects.create(fc=fc, geom=feature)

        update_simplified_geometries(fc.id)
        update_simplified_geometries(fc.id)
        self.assertEqual(len(self._points(fc.id)), 1)

        remove_simplified_geometries(fc.id)
        self.assertEqual(self._points(fc.id), [])


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


class ClusteredTileTests(ReplicaReadsTestMixin, TestCase):
    """A selection over the threshold is clusters in every tile; only selected
    collections count."""

    @staticmethod
    def _square(x, y, size=0.5):
        return Polygon(
            ((x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)), srid=4326
        )

    def _collection(self, name, origins):
        from features.matviews import update_simplified_geometries
        from features.models import FeatMap

        fc = make_feature_collection(name=name, path=name)
        for i, (x, y) in enumerate(origins):
            feature = Feature.objects.create(shape=self._square(x, y))
            FeatMap.objects.create(fc=fc, geom=feature, name=f"{name} {i}")
        update_simplified_geometries(fc.id)
        return fc

    def setUp(self):
        # All inside z2 tile 2/2/1 (lon 0..90, lat 0..66.5). "dense" has three
        # features, "sparse" one, "other" two; the threshold is patched to 3
        # below.
        self.dense = self._collection("dense", [(1, 1), (2, 1), (40, 40)])
        self.sparse = self._collection("sparse", [(10, 10)])
        self.other = self._collection("other", [(1.2, 1.2), (2.2, 1.2)])
        patcher = mock.patch("features.views.CLUSTER_MIN_FEATURES", 3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _multi(self, zxy, fcs):
        response = self.client.get(
            f"/api/features/multitiles/{zxy}.mvt?fc={','.join(str(fc.id) for fc in fcs)}"
        )
        self.assertEqual(response.status_code, 200)
        return decode_mvt_properties(response.content)

    @staticmethod
    def _shares(cluster):
        """{fc id: count} from a cluster's fc_<id> properties."""
        return {
            int(key[3:]): int(value)
            for key, value in cluster.items()
            if key.startswith("fc_")
        }

    def test_selection_over_the_threshold_is_all_clusters(self):
        # Four features between them: both collections become clusters, the
        # one-feature "sparse" included.
        layers = self._multi("2/2/1", [self.dense, self.sparse])

        clusters = layers["clusters"]
        self.assertEqual(sum(c["count"] for c in clusters), 4)
        self.assertEqual(
            sorted(sorted(self._shares(c).items()) for c in clusters),
            # (1,1), (2,1) and sparse's (10,10) share a grid cell at z2;
            # (40,40) does not.
            sorted([[(self.dense.id, 2), (self.sparse.id, 1)], [(self.dense.id, 1)]]),
        )
        self.assertNotIn("boundaries", layers)

    def test_collections_in_one_cell_share_one_cluster(self):
        # "other" sits in the cell holding dense's (1,1) and (2,1).
        layers = self._multi("2/2/1", [self.dense, self.other])
        [shared] = [c for c in layers["clusters"] if c["count"] == 4]
        self.assertEqual(self._shares(shared), {self.dense.id: 2, self.other.id: 2})
        self.assertEqual(len(layers["clusters"]), 2)

    def test_selection_under_the_threshold_is_polygons(self):
        layers = self._multi("2/2/1", [self.other])
        self.assertNotIn("clusters", layers)
        self.assertEqual(len(layers["boundaries"]), 2)

    def test_unselected_collections_add_nothing_to_the_counts(self):
        # "other" sits in the same cells as "dense" but is not requested.
        layers = self._multi("2/2/1", [self.dense])
        self.assertEqual(sum(c["count"] for c in layers["clusters"]), 3)
        self.assertNotIn("boundaries", layers)

    def test_threshold_counts_the_whole_selection(self):
        # Each under the threshold alone, three features together.
        layers = self._multi("2/2/1", [self.sparse, self.other])
        self.assertNotIn("boundaries", layers)
        self.assertEqual(sum(c["count"] for c in layers["clusters"]), 3)

    def test_every_tile_of_a_dense_selection_is_clusters(self):
        # At z4, (40,40) falls in another tile, leaving "dense" two features in
        # 4/8/7 -- under the threshold for the tile, but the selection is over
        # it, so this tile is clusters too.
        layers = self._multi("4/8/7", [self.dense])
        self.assertNotIn("boundaries", layers)
        self.assertEqual(sum(c["count"] for c in layers["clusters"]), 2)

    def test_no_clusters_above_max_zoom(self):
        from features.views import CLUSTER_MAX_ZOOM

        z = CLUSTER_MAX_ZOOM + 1
        # The tile holding lon 1.1, lat 1.1.
        x = int((1.1 + 180) / 360 * 2**z)
        y = 2**z // 2 - 1 - int(1.1 / 360 * 2**z)
        layers = self._multi(f"{z}/{x}/{y}", [self.dense])
        self.assertNotIn("clusters", layers)

    def _small(self, name, origins):
        from features.matviews import update_simplified_geometries
        from features.models import FeatMap

        fc = make_feature_collection(name=name, path=name)
        for x, y in origins:
            feature = Feature.objects.create(shape=self._square(x, y, size=0.01))
            FeatMap.objects.create(fc=fc, geom=feature)
        update_simplified_geometries(fc.id)
        return fc

    def test_high_zoom_tiles_cluster_from_points(self):
        # Above z6 clusters come from features_points, not the stored cells.
        # All three sit in z8 tile 8/128/127 (lon 0..1.41, lat 0..1.41).
        fc = self._small("village", [(1.1, 1.1), (1.2, 1.1), (1.3, 1.1)])
        layers = self._multi("8/128/127", [fc])
        self.assertEqual(sum(c["count"] for c in layers["clusters"]), 3)

    def test_stored_cells_and_points_agree(self):
        # The highest zoom that reads features_point_cells, and the four
        # children of one of its tiles, which read features_points, must count
        # the same features. All four points are inside z7 tile 7/64/63.
        from features.matviews import POINT_CELLS_LEVEL
        from features.views import _CLUSTER_GRID_BITS

        z = POINT_CELLS_LEVEL - _CLUSTER_GRID_BITS
        self.assertLessEqual(z, 7)
        x, y = 2 ** (z - 1), 2 ** (z - 1) - 1  # the tile NE of lon 0, lat 0
        fc = self._small("village", [(1.1, 1.1), (1.2, 1.1), (2.0, 2.0), (2.7, 0.5)])
        with mock.patch("features.views.CLUSTER_MIN_FEATURES", 1):
            parent = self._multi(f"{z}/{x}/{y}", [fc])
            children = [
                self._multi(f"{z + 1}/{2 * x + dx}/{2 * y + dy}", [fc])
                for dx in (0, 1)
                for dy in (0, 1)
            ]
        self.assertEqual(sum(c["count"] for c in parent["clusters"]), 4)
        self.assertEqual(
            sum(c["count"] for t in children for c in t.get("clusters", [])), 4
        )

    def test_single_collection_endpoint_clusters_too(self):
        body = self.client.get("/api/features/tiles/dense/2/2/1.mvt").content
        layers = decode_mvt_properties(body)
        self.assertEqual(sum(c["count"] for c in layers["clusters"]), 3)
        self.assertNotIn("dense", layers)

    def test_each_feature_is_counted_in_exactly_one_tile(self):
        # Centroids on the corner shared by all four z1 tiles (0, 0), on the
        # edge between two of them (lon 0), and inside one. Every tile with a
        # point clusters at threshold 1; the counts must add up to 3, not more.
        corner = self._collection("corner", [(-0.25, -0.25), (-0.25, 30), (60, 60)])
        total = 0
        with mock.patch("features.views.CLUSTER_MIN_FEATURES", 1):
            for x in (0, 1):
                for y in (0, 1):
                    layers = self._multi(f"1/{x}/{y}", [corner])
                    total += sum(c["count"] for c in layers.get("clusters", []))
        self.assertEqual(total, 3)
