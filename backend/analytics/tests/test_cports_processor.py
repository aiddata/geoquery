"""cports_v20_dynamic_filter_and_agg: filters and the outcome it adds up."""

from pathlib import Path

import geopandas as gpd
import shapely
from django.test import SimpleTestCase

from analytics.processors import cports_filter_agg as cp
from analytics.tests.extract_helpers import raster_dir


class CportsFilterAggTests(SimpleTestCase):
    def setUp(self):
        self.tmp = raster_dir()
        self.addCleanup(self.tmp.cleanup)
        gdf = gpd.GeoDataFrame(
            {
                "value": [100, 250, 4000],
                "Flow Class": ["ODA", "OOF", "ODA"],
            },
            # two projects inside the area, one outside it
            geometry=[shapely.Point(1, 1), shapely.Point(2, 2), shapely.Point(50, 50)],
            crs="EPSG:4326",
        )
        self.path = Path(self.tmp.name) / "cports.gpkg"
        gdf.to_file(self.path, layer=cp.TABLE_NAME, driver="GPKG")
        self.area = shapely.box(0, 0, 5, 5)

    def total(self, **kwargs):
        [(column, value)] = cp.cports_v20_dynamic_filter_and_agg(self.area, self.path, "cp", **kwargs)
        self.assertEqual(column, "cp")
        return value

    def test_adds_up_commitment_value_inside_the_area(self):
        self.assertEqual(self.total(), 350)

    def test_value_outcome_is_the_default(self):
        self.assertEqual(self.total(outcome="value"), self.total())

    def test_filters_narrow_the_records(self):
        flow = {"type": "categorical", "selected": ["ODA"], "aggregate": True}
        self.assertEqual(self.total(**{"Flow Class": flow}), 100)

    def test_unknown_outcome_is_rejected(self):
        with self.assertRaises(ValueError):
            self.total(outcome="project_count")
