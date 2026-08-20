import tempfile
from pathlib import Path

import numpy as np
import rasterio
import shapely
from django.test import SimpleTestCase
from rasterio.transform import from_origin

from analytics.processors import REGISTRY
from analytics.tasks.processing import get_func

# These names are persisted in ProcessingOption.function and in the dataset ingest
# JSON published in aiddata/geo-datasets. Renaming one silently breaks every existing
# extract task that references it, so the set is pinned here deliberately.
EXPECTED_PROCESSOR_NAMES = {
    "rasterstats_default_min",
    "rasterstats_default_max",
    "rasterstats_default_mean",
    "rasterstats_default_sum",
    "rasterstats_default_count",
    "rasterstats_default_categorical",
    "gcdf_v301_dynamic_filter_and_agg",
    "cports_v20_dynamic_filter_and_agg",
    "ged261_dynamic_filter_and_agg",
    "acled_dynamic_filter_and_agg",
    "landmarkmap_filter_and_agg",
}


def make_raster(directory, values):
    """Write a small single-band EPSG:4326 GeoTIFF and return its path."""
    path = Path(directory) / "test.tif"
    height, width = values.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=values.dtype,
        crs="EPSG:4326",
        transform=from_origin(0, height, 1, 1),
    ) as dst:
        dst.write(values, 1)
    return path


class RegistryTests(SimpleTestCase):
    def test_registry_names_are_stable(self):
        self.assertEqual(set(REGISTRY), EXPECTED_PROCESSOR_NAMES)

    def test_registry_keys_match_function_names(self):
        for name, func in REGISTRY.items():
            self.assertEqual(name, func.__name__)

    def test_get_func_returns_registered_callable(self):
        self.assertIs(
            get_func("rasterstats_default_mean"), REGISTRY["rasterstats_default_mean"]
        )

    def test_get_func_rejects_unknown_operation(self):
        with self.assertRaises(ValueError):
            get_func("not_a_real_processor")

    def test_get_func_rejects_incidental_names(self):
        # The previous dir()-based registry also exposed star-imported callables such
        # as itertools.product. The explicit registry must not.
        with self.assertRaises(ValueError):
            get_func("product")


class ZonalStatsTests(SimpleTestCase):
    def test_mean_over_full_extent(self):
        values = np.arange(16, dtype="float32").reshape(4, 4)
        with tempfile.TemporaryDirectory() as tmp:
            raster = make_raster(tmp, values)
            feat = shapely.box(0, 0, 4, 4)
            result = get_func("rasterstats_default_mean")(feat, raster, name="testcol")

        self.assertEqual(result, [("testcol", 7.5)])

    def test_count_and_sum_agree_with_numpy(self):
        values = np.arange(16, dtype="float32").reshape(4, 4)
        with tempfile.TemporaryDirectory() as tmp:
            raster = make_raster(tmp, values)
            feat = shapely.box(0, 0, 4, 4)
            total = get_func("rasterstats_default_sum")(feat, raster, name="s")
            count = get_func("rasterstats_default_count")(feat, raster, name="c")

        self.assertEqual(total, [("s", float(values.sum()))])
        self.assertEqual(count, [("c", values.size)])

    def test_categorical_fills_missing_categories_with_zero(self):
        values = np.array([[1, 1], [2, 2]], dtype="uint8")
        with tempfile.TemporaryDirectory() as tmp:
            raster = make_raster(tmp, values)
            feat = shapely.box(0, 0, 2, 2)
            result = get_func("rasterstats_default_categorical")(
                feat, raster, name="lc", category_map={1: "water", 2: "urban", 3: "ice"}
            )

        self.assertEqual(
            dict(result), {"lc_water": 2, "lc_urban": 2, "lc_ice": 0}
        )
