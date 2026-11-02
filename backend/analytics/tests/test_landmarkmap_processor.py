"""landmarkmap_filter_and_agg: candidate lookup and coverage share."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from django.test import SimpleTestCase

from analytics.processors import landmarkmap_filter_agg as lm
from analytics.tests.extract_helpers import raster_dir


def reference_share(gdf, feat):
    """The original computation: union every candidate, then intersect."""
    if gdf.empty or feat.area <= 0:
        return 0
    return gdf.geometry.union_all().intersection(feat).area / feat.area


class LandmarkmapFilterAggTests(SimpleTestCase):
    def setUp(self):
        self.tmp = raster_dir()
        self.addCleanup(self.tmp.cleanup)
        rng = np.random.default_rng(1)
        geoms, kinds = [], []
        # overlapping polygons across the whole world, so a union is needed
        # and most rows lie far from any one part of a spread feature
        for _ in range(400):
            x, y = rng.uniform(-178, 176), rng.uniform(-60, 60)
            geoms.append(shapely.box(x, y, x + rng.uniform(0.5, 3), y + rng.uniform(0.5, 3)))
            kinds.append(rng.choice(["indigenous", "community"]))
        geoms.append(shapely.Point(10.5, 10.5).buffer(1.2))
        kinds.append("indigenous")
        self.gdf = gpd.GeoDataFrame({"kind": kinds}, geometry=geoms, crs="EPSG:4326")
        self.path = Path(self.tmp.name) / "lm.gpkg"
        self.gdf.to_file(self.path, layer=lm.TABLE_NAME, driver="GPKG")

        # parts on both sides of the antimeridian, like the United States
        self.spread = shapely.MultiPolygon([
            shapely.box(-175, 50, -165, 58),
            shapely.box(170, 50, 178, 55),
            shapely.Point(10, 10).buffer(2),
        ])
        self.single = shapely.Polygon([(-20, -20), (25, -15), (30, 30), (-15, 25)])
        self.empty = shapely.box(-179.9, 80, -179.5, 80.4)

    def share(self, feat, **filters):
        [(column, value)] = lm.landmarkmap_filter_and_agg(feat, self.path, "lm", **filters)
        self.assertEqual(column, "lm")
        return value

    def test_share_matches_union_then_intersect(self):
        for label, feat in (("spread", self.spread), ("single", self.single)):
            with self.subTest(feature=label):
                expected = reference_share(self.gdf, feat)
                self.assertGreater(expected, 0)
                np.testing.assert_allclose(self.share(feat), expected, rtol=1e-9)

    def test_parts_are_looked_up_by_their_own_bounds(self):
        rowids = lm._candidate_rowids(self.path, self.spread)
        whole_box = lm._candidate_rowids(self.path, shapely.box(*self.spread.bounds))
        self.assertLess(len(rowids), len(whole_box) / 5)
        # every row that intersects the feature is still a candidate
        intersecting = set(np.flatnonzero(self.gdf.intersects(self.spread)) + 1)
        self.assertLessEqual(intersecting, set(rowids))

    def test_no_candidates_returns_zero_without_reading(self):
        self.assertEqual(lm._candidate_rowids(self.path, self.empty), [])
        self.assertEqual(self.share(self.empty), 0)
        result = lm.landmarkmap_filter_and_agg(
            self.empty, self.path, "lm",
            kind={"type": "categorical", "selected": ["indigenous", "community"],
                  "aggregate": False},
        )
        self.assertEqual(result, [("lm_indigenous", 0), ("lm_community", 0)])

    def test_aggregate_filter_matches_reference(self):
        filters = {"kind": {"type": "categorical", "selected": ["community"]}}
        expected = reference_share(self.gdf[self.gdf["kind"] == "community"], self.spread)
        np.testing.assert_allclose(self.share(self.spread, **filters), expected, rtol=1e-9)

    def test_non_aggregate_filter_gives_one_column_per_value(self):
        result = dict(lm.landmarkmap_filter_and_agg(
            self.single, self.path, "lm",
            kind={"type": "categorical", "selected": ["indigenous", "community"],
                  "aggregate": False},
        ))
        self.assertEqual(set(result), {"lm_indigenous", "lm_community"})
        for kind in ("indigenous", "community"):
            expected = reference_share(self.gdf[self.gdf["kind"] == kind], self.single)
            np.testing.assert_allclose(result[f"lm_{kind}"], expected, rtol=1e-9)

    def test_missing_index_falls_back_to_a_full_scan(self):
        with self.assertLogs(lm.logger, "WARNING"):
            self.assertIsNone(lm._candidate_rowids(Path(self.tmp.name) / "nope.gpkg", self.single))
