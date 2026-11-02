"""Precise rasterstats processors weight pixels by coverage and latitude."""

from unittest import mock

import numpy as np
import rasterstats.main
import shapely
from django.test import SimpleTestCase

from analytics.processors import BATCH_REGISTRY, REGISTRY
from analytics.tests.extract_helpers import raster_dir, write_raster


class PreciseProcessorTests(SimpleTestCase):
    def setUp(self):
        self.tmp = raster_dir()
        self.addCleanup(self.tmp.cleanup)
        # row 0 is the top (north) row, so the bottom row holds 90..99
        values = np.arange(100, dtype="float64").reshape(10, 10)
        self.raster = write_raster(self.tmp.name, "r.tif", values)
        self.high_lat = write_raster(self.tmp.name, "hl.tif", values, bounds=(0, 60, 10, 70))

    def value(self, function, feat, raster, **kwargs):
        [(column, value)] = REGISTRY[function](feat, raster, name="v", **kwargs)
        self.assertEqual(column, "v")
        return value

    def test_partial_pixels_are_weighted_by_coverage(self):
        # covers pixel 90 fully and pixel 91 half
        feat = shapely.box(0, 0, 1.5, 1)
        self.assertEqual(self.value("rasterstats_precise_count", feat, self.raster), 1.5)
        self.assertEqual(self.value("rasterstats_precise_sum", feat, self.raster), 135.5)
        self.assertAlmostEqual(
            self.value("rasterstats_precise_mean", feat, self.raster), 90.33333, places=5
        )
        # the default processors count both touched pixels in full
        self.assertEqual(self.value("rasterstats_default_count", feat, self.raster), 2)
        self.assertEqual(self.value("rasterstats_default_sum", feat, self.raster), 181.0)

    def test_mean_is_latitude_corrected_but_sum_is_not(self):
        # a full column: southern rows cover more area and hold larger values
        column = shapely.box(0, 60, 1, 70)
        default_mean = self.value("rasterstats_default_mean", column, self.high_lat)
        precise_mean = self.value("rasterstats_precise_mean", column, self.high_lat)
        self.assertEqual(default_mean, 45.0)
        self.assertGreater(precise_mean, default_mean)
        self.assertAlmostEqual(precise_mean, 48.08945, places=4)
        self.assertEqual(
            self.value("rasterstats_precise_sum", column, self.high_lat),
            self.value("rasterstats_default_sum", column, self.high_lat),
        )

    def test_kwargs_override_the_defaults(self):
        column = shapely.box(0, 60, 1, 70)
        self.assertEqual(
            self.value("rasterstats_precise_mean", column, self.high_lat, latitude_correction=False),
            45.0,
        )
        feat = shapely.box(0, 0, 1.25, 1)
        self.assertAlmostEqual(
            self.value("rasterstats_precise_count", feat, self.raster), 1.3, places=5
        )
        self.assertEqual(
            self.value("rasterstats_precise_count", feat, self.raster, percent_cover_scale=4), 1.25
        )

    def test_points_count_whole_pixels(self):
        # the fork disables percent cover for points
        point = shapely.Point(0.5, 0.5)
        count = self.value("rasterstats_precise_count", point, self.raster)
        self.assertEqual(count, 1)
        self.assertIsInstance(count, float)

    def test_count_is_always_a_float(self):
        # an empty window gives the fork an int 0; a mixed int/float column
        # would be typed by its first value downstream
        values = np.arange(100, dtype="float64").reshape(10, 10)
        raster = write_raster(self.tmp.name, "nd.tif", values, nodata=-9999)
        feat = shapely.box(20, 20, 21, 21)
        single = self.value("rasterstats_precise_count", feat, raster)
        self.assertEqual(single, 0)
        self.assertIsInstance(single, float)
        batch = BATCH_REGISTRY["rasterstats_precise_count"]
        [(column, value)] = list(batch([feat], raster, name="v"))[0][1]
        self.assertEqual(column, "v")
        self.assertEqual(value, 0)
        self.assertIsInstance(value, float)

    def test_split_features_match_unsplit_results(self):
        feat = shapely.Polygon([(0.33, 60.21), (9.61, 61.13), (8.77, 69.43), (1.27, 68.81)])
        real_split = rasterstats.main.split_geom
        tiles = []

        def recording_split(*args, **kwargs):
            pieces = list(real_split(*args, **kwargs))
            tiles.append(len(pieces))
            return pieces

        for function in (
            "rasterstats_precise_mean", "rasterstats_precise_sum", "rasterstats_precise_count"
        ):
            with self.subTest(processor=function):
                whole = self.value(function, feat, self.high_lat)
                tiles.clear()
                with mock.patch.object(rasterstats.main, "split_geom", side_effect=recording_split):
                    split = self.value(function, feat, self.high_lat, limit=9)
                self.assertGreater(tiles[0], 1)
                np.testing.assert_allclose(split, whole, rtol=1e-6)
