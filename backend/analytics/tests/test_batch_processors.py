"""Batch rasterstats processors match the single-feature ones exactly."""

from unittest import mock

import numpy as np
import shapely
from django.test import SimpleTestCase

from analytics.processors import BATCH_REGISTRY, REGISTRY
from analytics.processors import zonal_stats_rasterstats as zs
from analytics.tests.extract_helpers import raster_dir, write_raster


def square(x, y, size=1.0):
    return shapely.box(x, y, x + size, y + size)


class BatchEquivalenceTests(SimpleTestCase):
    def setUp(self):
        self.tmp = raster_dir()
        self.addCleanup(self.tmp.cleanup)
        values = np.arange(100, dtype="float64").reshape(10, 10)
        values[0, 0] = -9999
        self.raster = write_raster(self.tmp.name, "r.tif", values, nodata=-9999)
        categories = (np.arange(100).reshape(10, 10) % 3).astype("float64")
        self.categorical = write_raster(self.tmp.name, "c.tif", categories)
        self.features = [
            square(0, 0), square(2.5, 2.5, 3), square(9, 9), square(20, 20),  # outside: nodata
            shapely.Point(4.5, 4.5).buffer(1.5),
            # a point must not turn off percent cover for later features
            shapely.Point(1.5, 1.5), square(2.5, 2.5, 3),
        ]

    def test_every_rasterstats_processor_has_a_batch_form(self):
        self.assertEqual(
            set(BATCH_REGISTRY), {name for name in REGISTRY if name.startswith("rasterstats_")}
        )

    def test_batch_results_equal_single_feature_results(self):
        for name, batch in BATCH_REGISTRY.items():
            raster = self.categorical if name.endswith("categorical") else self.raster
            kwargs = {"name": "v"}
            if name.endswith("categorical"):
                kwargs["category_map"] = {0: "a", 1: "b", 2: "c"}
            with self.subTest(processor=name):
                single = [REGISTRY[name](f, raster, **dict(kwargs)) for f in self.features]
                batched = list(batch(self.features, raster, **dict(kwargs)))
                self.assertEqual([i for i, _ in batched], list(range(len(self.features))))
                self.assertEqual([r for _, r in batched], single)

    def test_a_failing_feature_is_isolated_and_the_rest_continue(self):
        broken = [self.features[0], "not a geometry", self.features[1]]
        results = list(BATCH_REGISTRY["rasterstats_default_mean"](broken, self.raster, name="v"))
        self.assertEqual([i for i, _ in results], [0, 1, 2])
        self.assertIsInstance(results[1][1], Exception)
        self.assertEqual(results[2][1], REGISTRY["rasterstats_default_mean"](self.features[1], self.raster, name="v"))

    def test_a_raster_that_will_not_open_fails_the_block_after_two_tries(self):
        missing = f"{self.tmp.name}/missing.tif"
        with mock.patch.object(zs, "_opens", wraps=zs._opens) as opens:
            results = list(BATCH_REGISTRY["rasterstats_default_mean"](self.features, missing, name="v"))
        self.assertEqual(len(results), len(self.features))
        self.assertTrue(all(isinstance(r, Exception) for _, r in results))
        self.assertEqual(opens.call_count, 2)

    def test_closing_early_releases_the_raster(self):
        iterator = BATCH_REGISTRY["rasterstats_default_mean"](self.features, self.raster, name="v")
        next(iterator)
        iterator.close()  # a stopping worker abandons the block
