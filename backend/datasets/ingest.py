"""Ingest a dataset (and its resources) from a JSON metadata file into the Django DB."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import rasterio
import shapely
import shapely.ops
from dateutil.relativedelta import relativedelta
from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction
from loguru import logger
from shapely.geometry import box

from datasets.models import Dataset, DatasetResource, Mapping
from analytics.models import ProcessingOption


def run_file_mask(fmask: str, fname: str):
    """Extract temporal data from a filename using a mask.

    Mask characters: Y = year digit, M = month digit, D = day digit.
    Returns (timestamp, date_str, step, date_type).
    """
    year = "".join(x for x, y in zip(fname, fmask) if y == "Y" and x.isdigit())
    month = "".join(x for x, y in zip(fname, fmask) if y == "M" and x.isdigit())
    day = "".join(x for x, y in zip(fname, fmask) if y == "D" and x.isdigit())

    if year == "":
        raise ValueError("No year found for data.")
    if len(year) != 4:
        raise ValueError("Invalid year.")
    if month != "" and len(month) != 2:
        raise ValueError("Invalid month.")
    if month != "" and day != "" and len(day) != 2:
        raise ValueError("Invalid day of month.")
    if month == "" and day != "" and len(day) != 3:
        raise ValueError("Invalid day of year.")

    if month == "" and day != "":
        date_str = f"{year}{day}"
        timestamp = datetime(int(year), 1, 1, tzinfo=timezone.utc) + timedelta(
            days=int(day) - 1
        )
    else:
        date_str = f"{year}{month}{day}"
        m = "01" if month == "" else month
        d = "01" if day == "" else day
        timestamp = datetime.strptime(f"{year}{m}{d}", "%Y%m%d").replace(
            tzinfo=timezone.utc
        )

    if len(date_str) == 7:
        step = relativedelta(days=1)
        date_type = "day of year"
    elif len(date_str) == 8:
        step = relativedelta(days=1)
        date_type = "year month day"
    elif len(date_str) == 6:
        step = relativedelta(months=1)
        date_type = "year month"
    elif len(date_str) == 4:
        step = relativedelta(years=1)
        date_type = "year"

    return timestamp, date_str, step, date_type


def get_raster_bbox(path) -> shapely.Geometry:
    """Return a shapely box for the spatial extent of a raster file."""
    logger.debug(f"Retrieving bounds of raster at {path}")
    with rasterio.open(path, "r") as raster:
        return box(*raster.bounds)


def _identify_and_create_resources(dataset: Dataset, dataset_path: Path):
    """Scan the filesystem for raster files and create DatasetResource rows.

    Returns a dict of derived dataset-level fields (temporal range, spatial extent).
    """
    file_mask = dataset.file_mask
    file_extension = dataset.file_extension

    if not dataset_path.is_dir():
        file_list = [dataset_path]
    else:
        file_list = list(dataset_path.rglob("*" + file_extension))

    if file_mask is None and len(file_list) != 1:
        raise ValueError("Multiple files found, but no file mask specified")
    if not file_list:
        raise ValueError("No files found")

    spatial_extent_bboxes = []
    temporal_info_list = []

    for f in file_list:
        resource_path = os.path.relpath(f, dataset_path)

        spatial_bbox = get_raster_bbox(f)
        spatial_extent_bboxes.append(spatial_bbox)
        spatial_wkt = spatial_bbox.wkt

        if file_mask is not None:
            timestamp, date_str, step, date_type = run_file_mask(
                file_mask, resource_path
            )
            temporal_info_list.append((timestamp, date_str, step, date_type))

            DatasetResource.objects.update_or_create(
                name=f"{dataset.name}_{date_str}",
                defaults={
                    "dataset": dataset,
                    "path": resource_path,
                    "temporal": timestamp,
                    "label": date_str,
                    "spatial_extent": GEOSGeometry(spatial_wkt, srid=4326),
                },
            )
        else:
            DatasetResource.objects.update_or_create(
                name=f"{dataset.name}_none",
                defaults={
                    "dataset": dataset,
                    "path": resource_path,
                    "temporal": None,
                    "label": None,
                    "spatial_extent": GEOSGeometry(spatial_wkt, srid=4326),
                },
            )

    # Derive dataset-level temporal / spatial fields from resources
    if file_mask is None:
        temporal_name = "Temporally Invariant"
        temporal_start = None
        temporal_end = None
        temporal_type = None
    else:
        temporal_name = "Datetime"
        temporal_start = min(t[0] for t in temporal_info_list)
        temporal_end = max(t[0] for t in temporal_info_list)
        temporal_type = temporal_info_list[0][3]

    spatial_extent = shapely.ops.unary_union(spatial_extent_bboxes).wkt

    return {
        "temporal_start": temporal_start,
        "temporal_end": temporal_end,
        "temporal_name": temporal_name,
        "temporal_type": temporal_type,
        "spatial_extent": GEOSGeometry(spatial_extent, srid=4326),
    }


def _sync_mappings(dataset: Dataset, mappings: dict[str, int] | None):
    """Replace all Mapping rows for *dataset* with those in *mappings*."""
    dataset.mappings.all().delete()
    if mappings:
        Mapping.objects.bulk_create(
            [
                Mapping(dataset=dataset, map_name=key, map_val=val)
                for key, val in mappings.items()
            ]
        )


# JSON keys that don't map directly to Dataset model fields
_NON_MODEL_KEYS = {"mappings", "processing_options", "coverage_dependency", "is_global"}


def _dataset_fields_from_json(data: dict) -> dict:
    """Return a dict of kwargs suitable for Dataset.objects.create / update."""
    model_field_names = {f.name for f in Dataset._meta.get_fields()}

    fields = {}
    skipped = []
    for key, val in data.items():
        if key in _NON_MODEL_KEYS:
            continue
        if key not in model_field_names:
            skipped.append(key)
            continue
        fields[key] = val

    if skipped:
        logger.warning(
            f"Ignoring unrecognized keys (not in Dataset model): {', '.join(skipped)}"
        )

    # mapped is derived
    fields["mapped"] = bool(data.get("mappings"))

    return fields


@transaction.atomic
def ingest_dataset(
    json_data: dict | Path,
    update: bool = False,
    update_or_insert: bool = False,
) -> Dataset:
    """Ingest a dataset into the Django-managed database.

    Parameters
    ----------
    json_data:
        A dict of dataset metadata, or a Path to a JSON file.
    update:
        Update an existing dataset (raises if not found).
    update_or_insert:
        Try to update, falling back to insert.
    """
    if isinstance(json_data, Path):
        logger.info(f"Reading JSON from {json_data}")
        data = json.loads(json_data.read_text())
    elif isinstance(json_data, dict):
        logger.info("Reading JSON from dict")
        data = json_data
    else:
        raise TypeError("json_data must be a dict or Path")

    fields = _dataset_fields_from_json(data)
    name = fields["name"]
    dataset_path = Path(fields["path"])

    if update_or_insert:
        dataset, created = Dataset.objects.update_or_create(
            name=name,
            defaults=fields,
        )
        logger.info(f"{'Inserted' if created else 'Updated'} dataset {name!r}")
    elif update:
        rows = Dataset.objects.filter(name=name).update(**fields)
        if rows == 0:
            raise ValueError(f"Dataset {name!r} not found for update")
        dataset = Dataset.objects.get(name=name)
        logger.info(f"Updated dataset {name!r}")
    else:
        dataset = Dataset.objects.create(**fields)
        logger.info(f"Inserted dataset {name!r}")

    # Mappings
    _sync_mappings(dataset, data.get("mappings"))

    # Scan filesystem, create/update resources, derive spatial/temporal
    derived = _identify_and_create_resources(dataset, dataset_path)

    # Patch the dataset with derived spatial/temporal fields
    for attr, val in derived.items():
        setattr(dataset, attr, val)
    dataset.save()

    logger.success(f"Finished dataset ingest for {name!r}")

    # add processing options or update if they already exist
    if not data.get("processing_options"):
        logger.info(f"No processing options provided for dataset {name!r}")
        return dataset

    for po in data["processing_options"]:
        po_fields = {
            "dataset": dataset,
            "short_name": po["short_name"],
            "description": po.get("description", ""),
            "function": po["function"],
            "result_type": po.get("result_type"),
            "kwargs": po.get("kwargs", {}),
            "active": po.get("active", False),
            "public": po.get("public", False),
        }
        ProcessingOption.objects.update_or_create(
            dataset=dataset,
            short_name=po["short_name"],
            defaults=po_fields,
        )
        logger.info(
            f"Added/updated processing option {po['short_name']!r} for dataset {name!r}"
        )

    logger.success(f"Finished adding processing_options for dataset {name!r}")

    return dataset
