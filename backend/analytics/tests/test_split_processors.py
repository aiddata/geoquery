"""Default rasterstats processors split large features without changing results."""

from unittest import mock

import numpy as np
import rasterstats.main
import shapely
from django.test import SimpleTestCase

from analytics.processors import BATCH_REGISTRY, REGISTRY
from analytics.processors import zonal_stats_rasterstats as zs
from analytics.tests.extract_helpers import raster_dir, write_raster

STATS = ("min", "max", "mean", "sum", "count")


class SplitDefaultProcessorTests(SimpleTestCase):
    def setUp(self):
        self.tmp = raster_dir()
        self.addCleanup(self.tmp.cleanup)
        rng = np.random.default_rng(0)
        values = rng.uniform(-50, 50, (40, 40))
        values[5:9, 12:30] = -9999  # nodata straddling tile seams
        self.raster = write_raster(self.tmp.name, "r.tif", values, nodata=-9999)
        # irregular edges, a hole and a second part, so all_touched pixels
        # fall on tile seams
        self.feature = shapely.MultiPolygon([
            shapely.Polygon(
                [(1.3, 2.7), (37.1, 1.9), (38.6, 36.2), (2.2, 38.8)],
                [[(15.5, 15.5), (24.4, 15.9), (20.1, 24.7)]],
            ),
            shapely.box(0.2, 39.1, 3.7, 39.9),
        ])
        self.tiles = []
        real_split = rasterstats.main.split_geom

        def recording_split(*args, **kwargs):
            pieces = list(real_split(*args, **kwargs))
            self.tiles.append(len(pieces))
            return pieces

        patcher = mock.patch.object(rasterstats.main, "split_geom", side_effect=recording_split)
        patcher.start()
        self.addCleanup(patcher.stop)

    def single(self, stat, **kwargs):
        [(_, value)] = REGISTRY[f"rasterstats_default_{stat}"](
            self.feature, self.raster, name="v", **kwargs
        )
        return value

    def batch(self, stat, **kwargs):
        batch = BATCH_REGISTRY[f"rasterstats_default_{stat}"]
        [(_, [(_, value)])] = list(batch([self.feature], self.raster, name="v", **kwargs))
        return value

    def test_split_results_match_unsplit_results(self):
        for form in (self.single, self.batch):
            for stat in STATS:
                with self.subTest(form=form.__name__, stat=stat):
                    whole = form(stat, limit=0)
                    self.tiles.clear()
                    split = form(stat, limit=25)
                    self.assertGreater(self.tiles[0], 1)
                    if stat == "count":
                        self.assertEqual(split, whole)
                    else:
                        np.testing.assert_allclose(split, whole, rtol=1e-9)

    def test_large_features_are_split_by_default(self):
        with mock.patch.object(zs, "DEFAULT_LIMIT", 25):
            self.single("mean")
            self.batch("mean")
        self.assertEqual(len(self.tiles), 2)
        self.assertTrue(all(n > 1 for n in self.tiles))

    def test_features_under_the_default_limit_are_not_split(self):
        self.single("mean")
        self.assertEqual(self.tiles, [1])

    def test_kwargs_override_the_default_limit(self):
        with mock.patch.object(zs, "DEFAULT_LIMIT", 25):
            self.single("mean", limit=0)
        # limit=0 means never split: split_geom is not called at all
        self.assertEqual(self.tiles, [])
