"""A small world to run tools against.

One country with two districts, one raster dataset with two years and two
extract types, and completed extracts for some of it. Deliberately not
complete: the second district is missing 2020 values so the partial-column
flag has something real to detect.
"""

from __future__ import annotations

from datetime import datetime, timezone

from django.contrib.gis.geos import Polygon

from analytics.models import (
    ExtractData,
    ExtractTask,
    ProcessingOption,
    Request,
    RequestMap,
)
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection


def make_fc(name="gB_v6_TST_ADM1", **kwargs):
    kwargs.setdefault("path", f"/data/boundaries/{name}.gpkg")
    kwargs.setdefault("active", True)
    kwargs.setdefault("public", True)
    kwargs.setdefault("title", "Testland ADM1")
    kwargs.setdefault("group_level", 1)
    kwargs.setdefault("source_name", "geoBoundaries")
    kwargs.setdefault("source_url", "https://www.geoboundaries.org/")
    kwargs.setdefault("license", "CC BY 4.0")
    kwargs.setdefault("license_url", "https://creativecommons.org/licenses/by/4.0/")
    kwargs.setdefault("citation", "Runfola, D. et al. (2020). geoBoundaries.")
    return FeatureCollection.objects.create(name=name, **kwargs)


def make_dataset(name="esa_landcover", **kwargs):
    kwargs.setdefault("path", f"/data/rasters/{name}")
    kwargs.setdefault("type", "raster")
    kwargs.setdefault("active", True)
    kwargs.setdefault("public", True)
    kwargs.setdefault("title", "ESA Land Cover")
    kwargs.setdefault("is_global", True)
    kwargs.setdefault("source_name", "ESA CCI")
    kwargs.setdefault("source_url", "https://climate.esa.int/")
    kwargs.setdefault("license", "ESA CCI Data Policy")
    kwargs.setdefault("license_url", "https://climate.esa.int/en/data/access/")
    kwargs.setdefault("citation", "Defourny, P. (2017). Land Cover Maps v2.0.7.")
    kwargs.setdefault("temporal_start", datetime(2015, 1, 1, tzinfo=timezone.utc))
    kwargs.setdefault("temporal_end", datetime(2020, 1, 1, tzinfo=timezone.utc))
    return Dataset.objects.create(name=name, **kwargs)


def square(x: float, y: float, size: float = 1.0) -> Polygon:
    return Polygon(
        ((x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)),
        srid=4326,
    )


class World:
    """Fixture world, built in one call. Attributes are what tests assert on."""

    def __init__(self):
        self.fc = make_fc()
        self.dataset = make_dataset()
        self.resources = {
            year: DatasetResource.objects.create(
                dataset=self.dataset,
                name=f"esa_lc_{year}",
                path=f"{year}.tif",
                label=str(year),
                temporal=datetime(year, 1, 1, tzinfo=timezone.utc),
            )
            for year in (2015, 2020)
        }
        self.pos = {
            short: ProcessingOption.objects.create(
                dataset=self.dataset,
                short_name=short,
                function=f"f_{short}",
                description=f"{short} of pixel values",
                active=True,
                public=True,
            )
            for short in ("mean", "count")
        }

        self.features = []
        self.fms = []
        for i, name in enumerate(("Northshire", "Southshire")):
            feature = Feature.objects.create(shape=square(i * 2.0, 0.0))
            self.features.append(feature)
            self.fms.append(
                FeatMap.objects.create(
                    fc=self.fc, geom=feature, name=name, attr={"code": f"T{i}"}
                )
            )
        self.tasks = []

    def extract(self, fm, po, resource, value, name="mean"):
        """One completed extract: the task plus its single-position values."""
        task = ExtractTask.objects.create(
            dataset_id=self.dataset.id,
            resource_ids=[resource.id],
            fm=fm,
            po=po,
            status=1,
        )
        ExtractData.objects.create(
            extract_task=task,
            dataset_id=self.dataset.id,
            name=name,
            data_column="float",
            float_values=[value],
        )
        self.tasks.append(task)
        return task

    def fill(self):
        """Complete 2015 for both districts, 2020 for the first only.

        The asymmetry is the point: it makes ``esa_lc_2020.mean`` a partially
        processed column, which several tools have to report.
        """
        self.extract(self.fms[0], self.pos["mean"], self.resources[2015], 10.0)
        self.extract(self.fms[1], self.pos["mean"], self.resources[2015], 20.0)
        self.extract(self.fms[0], self.pos["mean"], self.resources[2020], 14.0)
        return self

    def simplify(self):
        """Populate the pre-simplified geometry tables for this collection.

        geometry.py reads only from those tables, so without this every
        GeoJSON test would pass against empty geometry and prove nothing.
        """
        from features.matviews import update_simplified_geometries

        update_simplified_geometries(self.fc.id)
        return self

    def make_request(self, user=None, status=1, contact="a@example.com"):
        request = Request.objects.create(
            contact=contact,
            user=user,
            custom_name="Test export",
            status=status,
            source="mcp",
            data={
                "selection_label": self.fc.title,
                "feature_ids": [f.id for f in self.features],
                "datasets": [
                    {"dataset_name": self.dataset.name, "extract_types": ["mean"]}
                ],
            },
        )
        RequestMap.objects.bulk_create(
            [
                RequestMap(request=request, task=t, dataset_id=self.dataset.id)
                for t in self.tasks
            ]
        )
        return request
