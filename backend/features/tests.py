import math
import struct
from unittest import mock

from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.db import connection
from django.test import SimpleTestCase, TestCase
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


def tile_at(z, lon, lat):
    """z/x/y of the web mercator tile holding lon, lat."""
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return f"{z}/{x}/{y}"


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

    Geometry is skipped, except that a single point is given as `_point`:
    (x, y) in tile units, 0..4096, y down.
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
            tags, geom_type, geometry = [], None, []
            for f, wire, v in _fields(feature):
                if f in (2, 4):
                    j, ints = 0, tags if f == 2 else geometry
                    while j < len(v):
                        t, j = _varint(v, j)
                        ints.append(t)
                elif f == 3:
                    geom_type = v
            props = {keys[k]: values[t] for k, t in zip(tags[::2], tags[1::2])}
            if geom_type == 1 and len(geometry) == 3:
                # One MoveTo: zigzag-encoded x, y in tile units, y down.
                props["_point"] = tuple((g >> 1) ^ -(g & 1) for g in geometry[1:])
            decoded.append(props)
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


class ClusterHierarchyTests(SimpleTestCase):
    """features.clusters.build_hierarchy, on points in EPSG:3857 metres."""

    @staticmethod
    def _cloud(seed, count, x0, y0, spread):
        import numpy as np

        rng = np.random.default_rng(seed)
        return x0 + rng.random(count) * spread, y0 + rng.random(count) * spread

    def test_every_level_holds_every_point(self):
        from features.clusters import CLUSTER_MAX_ZOOM, build_hierarchy

        x, y = self._cloud(0, 5000, 7.5e6, 2.5e6, 4e5)
        levels = build_hierarchy(x, y)
        self.assertEqual(len(levels), CLUSTER_MAX_ZOOM + 1)
        for lx, ly, ln in levels:
            self.assertEqual(int(ln.sum()), 5000)
            self.assertEqual(len(lx), len(ly))
        # Coarser zooms have no more clusters than finer ones.
        sizes = [len(ln) for _, _, ln in levels]
        self.assertEqual(sizes, sorted(sizes))

    def test_points_within_the_radius_merge_and_far_ones_do_not(self):
        from features.clusters import CLUSTER_MAX_ZOOM, build_hierarchy, radius

        r = radius(CLUSTER_MAX_ZOOM)
        # Two points a quarter radius apart, and one ten radii away; on both
        # sides of 0, where grid cells change sign.
        x = [-r / 8, r / 8, 10 * r]
        y = [0.0, 0.0, 0.0]
        lx, _, ln = build_hierarchy(x, y)[CLUSTER_MAX_ZOOM]
        self.assertEqual(sorted(ln.tolist()), [1, 2])
        self.assertAlmostEqual(lx[ln == 2][0], 0, delta=r / 8)
        # At zoom 0 the radius spans all three.
        self.assertEqual(build_hierarchy(x, y)[0][2].tolist(), [3])

    def test_input_order_does_not_matter(self):
        import numpy as np

        from features.clusters import build_hierarchy

        x, y = self._cloud(1, 500, -3e6, 1e6, 1e5)
        flip = np.arange(500)[::-1]
        for a, b in zip(build_hierarchy(x, y), build_hierarchy(x[flip], y[flip])):
            for u, v in zip(a, b):
                np.testing.assert_array_equal(u, v)

    def test_points_beyond_the_mercator_world_are_clamped_to_its_edge(self):
        # A polar centroid (Antarctica's) is far south of the tiled world;
        # clamped, the last row of tiles still counts it.
        from features.clusters import WEB_MERCATOR_HALF_WIDTH as w
        from features.clusters import build_hierarchy

        _, ly, ln = build_hierarchy([0.0], [-43e6])[0]
        self.assertEqual((ly.tolist(), ln.tolist()), ([-w], [1]))

    def test_no_points(self):
        from features.clusters import build_hierarchy

        for lx, _, ln in build_hierarchy([], []):
            self.assertEqual((len(lx), len(ln)), (0, 0))


class ClusteredTileTests(ReplicaReadsTestMixin, TestCase):
    """A selection over the threshold is clusters in every tile up to
    CLUSTER_MAX_ZOOM, merged across collections exactly as the whole
    selection would be."""

    @staticmethod
    def _square(x, y, size=0.01):
        return Polygon(
            ((x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)), srid=4326
        )

    def _collection(self, name, origins, **fields):
        from features.matviews import update_simplified_geometries
        from features.models import FeatMap

        fc = make_feature_collection(name=name, path=name, **fields)
        for i, (x, y) in enumerate(origins):
            feature = Feature.objects.create(shape=self._square(x, y))
            FeatMap.objects.create(fc=fc, geom=feature, name=f"{name} {i}")
        update_simplified_geometries(fc.id)
        return fc

    @staticmethod
    def _scatter(seed, count, lon0, lat0, spread):
        import random

        rng = random.Random(seed)
        return [
            (lon0 + rng.random() * spread, lat0 + rng.random() * spread) for _ in range(count)
        ]

    def setUp(self):
        # Three overlapping collections around lon 0..8, lat 0..8, which
        # straddle tile edges at every zoom (lon 0 and lat 0 are edges at all
        # of them). The threshold is patched to 10 below.
        self.big = self._collection("big", self._scatter(1, 60, -2, -2, 8))
        self.mid = self._collection("mid", self._scatter(2, 20, -1, -1, 6))
        self.small = self._collection("small", self._scatter(3, 4, 0, 0, 4))
        self.fcs = [self.big, self.mid, self.small]
        patcher = mock.patch("features.views.CLUSTER_MIN_FEATURES", 10)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _tile(self, z, x, y, fcs):
        response = self.client.get(
            f"/api/features/multitiles/{z}/{x}/{y}.mvt"
            f"?fc={','.join(str(fc.id) for fc in fcs)}"
        )
        self.assertEqual(response.status_code, 200)
        return decode_mvt_properties(response.content)

    @staticmethod
    def _shares(cluster):
        """{fc id: count} from a cluster's fc_<id> properties."""
        return {
            int(key[3:]): int(value) for key, value in cluster.items() if key.startswith("fc_")
        }

    def _all_tiles(self, z, fcs):
        """Every cluster at zoom z, from every tile over lon -3..7, lat -3..7."""
        x0, y1 = (int(v) for v in tile_at(z, -3, -3).split("/")[1:])
        x1, y0 = (int(v) for v in tile_at(z, 7, 7).split("/")[1:])
        clusters = []
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                clusters += self._tile(z, x, y, fcs).get("clusters", [])
        return clusters

    def _reference(self, z, fcs):
        """The merge of the whole selection at zoom z, straight from the rule
        in features.views, as sorted (count, shares) pairs."""
        from features.clusters import radius

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, fc_id, n, ST_X(pt), ST_Y(pt) FROM features_cluster_points"
                " WHERE fc_id = ANY(%s::integer[]) AND z = %s",
                [[fc.id for fc in fcs], z],
            )
            rows = cursor.fetchall()
        r2 = radius(z) ** 2

        def near(a, b):
            return a[1] != b[1] and (a[3] - b[3]) ** 2 + (a[4] - b[4]) ** 2 <= r2

        def weight(row):
            return (row[2], row[0])

        anchors = {
            a[0] for a in rows if not any(near(a, b) and weight(b) > weight(a) for b in rows)
        }
        groups = {}
        for row in rows:
            heads = [b for b in rows if b[0] in anchors and near(row, b)]
            head = row[0] if row[0] in anchors or not heads else max(heads, key=weight)[0]
            shares = groups.setdefault(head, {})
            shares[row[1]] = shares.get(row[1], 0) + row[2]
        return sorted((sum(s.values()), sorted(s.items())) for s in groups.values())

    def test_tiles_match_the_whole_selection_merge(self):
        from features.clusters import CLUSTER_MAX_ZOOM

        for z in range(2, CLUSTER_MAX_ZOOM + 1):
            with self.subTest(z=z):
                tiles = sorted(
                    (c["count"], sorted(self._shares(c).items()))
                    for c in self._all_tiles(z, self.fcs)
                )
                self.assertEqual(tiles, self._reference(z, self.fcs))

    def test_collections_merge_into_each_other(self):
        # At zoom 2 the radius is 11 degrees: everything is one cluster.
        [cluster] = self._all_tiles(2, self.fcs)
        self.assertEqual(
            self._shares(cluster), {self.big.id: 60, self.mid.id: 20, self.small.id: 4}
        )

    def test_a_collection_alone_is_drawn_as_stored(self):
        from features.clusters import CLUSTER_MAX_ZOOM

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT n FROM features_cluster_points WHERE fc_id = %s AND z = %s",
                [self.big.id, CLUSTER_MAX_ZOOM],
            )
            stored = sorted(n for (n,) in cursor.fetchall())
        tiles = self._all_tiles(CLUSTER_MAX_ZOOM, [self.big])
        self.assertEqual(sorted(c["count"] for c in tiles), stored)
        self.assertTrue(all(self._shares(c) == {self.big.id: c["count"]} for c in tiles))

    def test_selection_under_the_threshold_is_polygons(self):
        # At z6: the test squares are too small to survive the z0-5 tier.
        lon, lat = self._scatter(3, 1, 0, 0, 4)[0]
        z, x, y = (int(v) for v in tile_at(6, lon + 0.005, lat + 0.005).split("/"))
        layers = self._tile(z, x, y, [self.small])
        self.assertNotIn("clusters", layers)
        self.assertIn("boundaries", layers)

    def test_threshold_counts_the_whole_selection(self):
        # mid (20) + small (4) clears a threshold of 21; mid alone does not.
        with mock.patch("features.views.CLUSTER_MIN_FEATURES", 21):
            self.assertNotIn("clusters", self._tile(2, 2, 1, [self.mid]))
            self.assertIn("clusters", self._tile(2, 2, 1, [self.mid, self.small]))

    def test_polygons_above_max_zoom(self):
        from features.clusters import CLUSTER_MAX_ZOOM

        z = CLUSTER_MAX_ZOOM + 1
        lon, lat = self._scatter(1, 1, -2, -2, 8)[0]
        zxy = tile_at(z, lon + 0.005, lat + 0.005)
        layers = decode_mvt_properties(
            self.client.get(f"/api/features/multitiles/{zxy}.mvt?fc={self.big.id}").content
        )
        self.assertNotIn("clusters", layers)
        self.assertIn("boundaries", layers)

    def test_single_collection_endpoint_clusters_too(self):
        layers = decode_mvt_properties(
            self.client.get("/api/features/tiles/big/2/2/1.mvt").content
        )
        self.assertNotIn("big", layers)
        self.assertGreater(sum(c["count"] for c in layers["clusters"]), 0)

    def test_refresh_replaces_and_remove_deletes_the_clusters(self):
        from features.matviews import remove_simplified_geometries, update_simplified_geometries

        def stored():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(DISTINCT z), sum(n) FROM features_cluster_points"
                    " WHERE fc_id = %s",
                    [self.small.id],
                )
                return cursor.fetchone()

        from features.clusters import CLUSTER_MAX_ZOOM

        update_simplified_geometries(self.small.id)
        self.assertEqual(stored(), (CLUSTER_MAX_ZOOM + 1, 4 * (CLUSTER_MAX_ZOOM + 1)))
        remove_simplified_geometries(self.small.id)
        self.assertEqual(stored(), (0, None))


class GeoboundariesTitleTests(TestCase):
    def test_collection_title_appends_known_canonical(self):
        from features.management.commands.ingest_geoboundaries import collection_title

        def title(canonical):
            return collection_title(
                {"title": "geoBoundaries v6 - Ghana ADM2", "other": {"boundaryCanonical": canonical}}
            )

        self.assertEqual(title("Districts"), "geoBoundaries v6 - Ghana ADM2 (Districts)")
        self.assertEqual(title("  Districts "), "geoBoundaries v6 - Ghana ADM2 (Districts)")
        for missing in ("", "   ", "Unknown", "unknown", "gbOpen", "nan", None):
            self.assertEqual(title(missing), "geoBoundaries v6 - Ghana ADM2", missing)
        self.assertEqual(
            collection_title({"title": "geoBoundaries v6 - Ghana ADM2", "other": {}}),
            "geoBoundaries v6 - Ghana ADM2",
        )

        def adm0(canonical):
            return collection_title(
                {
                    "title": "geoBoundaries v6 - Ghana ADM0",
                    "other": {"boundaryType": "ADM0", "boundaryCanonical": canonical},
                }
            )

        self.assertEqual(adm0("Republic"), "geoBoundaries v6 - Ghana ADM0 (Republic)")
        for missing in ("", "Unknown", "gbOpen", None):
            self.assertEqual(adm0(missing), "geoBoundaries v6 - Ghana ADM0 (Country)", missing)

    def test_migration_updates_existing_titles_once_and_reverses(self):
        import importlib

        migration = importlib.import_module(
            "features.migrations.0015_geoboundaries_canonical_titles"
        )
        rows = {
            "gB_57dcd43_GHA_ADM2": ("ADM2", "Districts"),
            "gB_57dcd43_GHA_ADM1": ("ADM1", "Unknown"),
            "gB_57dcd43_BIH_ADM2": ("ADM2", "gbOpen"),
            "gB_57dcd43_BIH_ADM0": ("ADM0", "gbOpen"),
            "gB_57dcd43_BEN_ADM0": ("ADM0", ""),
            "gB_57dcd43_TGO_ADM0": ("ADM0", "Republic"),
            "other_GHA_ADM2": ("ADM2", "Districts"),
        }
        for name, (level, canonical) in rows.items():
            FeatureCollection.objects.create(
                name=name, path=f"/{name}", title=f"T {name}",
                other={"boundaryType": level, "boundaryCanonical": canonical},
            )
        FeatureCollection.objects.create(
            name="gB_57dcd43_NOM_ADM1", path="/none", title="T none", other={}
        )
        changed = {
            "gB_57dcd43_GHA_ADM2": "T gB_57dcd43_GHA_ADM2 (Districts)",
            "gB_57dcd43_BIH_ADM0": "T gB_57dcd43_BIH_ADM0 (Country)",
            "gB_57dcd43_BEN_ADM0": "T gB_57dcd43_BEN_ADM0 (Country)",
            "gB_57dcd43_TGO_ADM0": "T gB_57dcd43_TGO_ADM0 (Republic)",
        }

        def titles():
            return dict(FeatureCollection.objects.values_list("name", "title"))

        before = titles()
        with connection.cursor() as cursor:
            cursor.execute(migration.FORWARD)
            cursor.execute(migration.FORWARD)
        after = titles()
        self.assertEqual(after, {**before, **changed})
        with connection.cursor() as cursor:
            cursor.execute(migration.REVERSE)
        self.assertEqual(titles(), before)
