"""Shared fixtures for extraction tests: inputs, settled input states, rasters."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from django.contrib.gis.geos import Point, Polygon
from django.db import transaction

from analytics.changes import COLLECTION, DATASET, mark
from analytics.models import ExtractInvalidItem, ProcessingOption
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection


def settle_inputs():
    """Reconcile every dirty input scope, as beat would, so work on it may run.

    Creating a dataset, resource, option or feature marks its scope dirty
    (migration 0031's triggers), and dirty scopes are not processed. Tests
    that exercise processing call this after setting up their inputs.
    """
    from analytics.sync import run_until_clean

    return run_until_clean()


def reset_dataset_inputs(dataset_id, **fields):
    """Edit a dataset and record a whole-dataset reset, as invalidate_extract_inputs does."""
    with transaction.atomic():
        Dataset.objects.filter(id=dataset_id).update(**fields)
        mark(DATASET, [dataset_id], rewind_from=0, sync_pairs=True, reset_tasks=True)


def reset_resource_inputs(resource_id, **fields):
    """Edit a resource and record a targeted reset of its tasks."""
    with transaction.atomic():
        DatasetResource.objects.filter(id=resource_id).update(**fields)
        dataset_id = DatasetResource.objects.values_list("dataset_id", flat=True).get(id=resource_id)
        mark(DATASET, [dataset_id], items=(ExtractInvalidItem.RESOURCE, [resource_id]))


def reset_feature_shape(geom_id, shape):
    """Edit a geometry and record a targeted reset of every feature using it."""
    with transaction.atomic():
        Feature.objects.filter(id=geom_id).update(shape=shape)
        by_collection = {}
        for fm_id, fc_id in FeatMap.objects.filter(geom_id=geom_id).values_list("id", "fc_id"):
            by_collection.setdefault(fc_id, []).append(fm_id)
        for fc_id, fm_ids in sorted(by_collection.items()):
            mark(COLLECTION, [fc_id], items=(ExtractInvalidItem.FEATURE, fm_ids))


def make_dataset(name, *, resources=1, is_global=True, period=None, active=True,
                 function="rasterstats_default_mean", extent=None, path=None, temporal=None):
    """A dataset with ``resources`` resources and one active "mean" option."""
    dataset = Dataset.objects.create(
        name=name, path=path or f"/data/{name}", active=active, is_global=is_global,
        task_group_period=period, type="raster", spatial_extent=extent,
    )
    option = ProcessingOption.objects.create(
        dataset=dataset, short_name="mean", function=function, active=True,
    )
    made = []
    for i in range(resources):
        when = temporal[i] if temporal else datetime(2020, 1 + i % 12, 1, tzinfo=timezone.utc) \
            .replace(year=2020 + i // 12)
        made.append(DatasetResource.objects.create(
            dataset=dataset, name=f"{name}-r{i}", path=f"r{i}.tif", temporal=when,
        ))
    return dataset, option, made


def make_collection(name, count=1, *, active=True, upload=False, points=None):
    """A collection of ``count`` features (unit squares unless ``points`` given)."""
    fc = FeatureCollection.objects.create(
        name=name, path=f"/data/{name}", active=active, is_user_upload=upload,
    )
    fms = []
    for i in range(count):
        if points is not None:
            shape = Point(*points[i])
        else:
            shape = Polygon(((i, 0), (i + 1, 0), (i + 1, 1), (i, 1), (i, 0)))
        fms.append(FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=shape)))
    return fc, fms


def write_raster(directory, name, values, *, bounds=(0, 0, 10, 10), nodata=None):
    """Write a single-band float GeoTIFF of ``values`` spanning ``bounds``."""
    import rasterio
    from rasterio.transform import from_bounds

    array = np.asarray(values, dtype="float64")
    path = Path(directory) / name
    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
        dtype="float64", crs="EPSG:4326", nodata=nodata,
        transform=from_bounds(*bounds, array.shape[1], array.shape[0]),
    ) as dst:
        dst.write(array, 1)
    return path


def raster_dir():
    """A temporary directory that is removed with the returned object."""
    return tempfile.TemporaryDirectory()
