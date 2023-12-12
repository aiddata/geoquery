import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import rasterio
import shapely
from dateutil.relativedelta import relativedelta
from loguru import logger
from psycopg.types.json import Json, Jsonb
from shapely.geometry import box

from gqcore.utils.db.conn import get_conn
from gqcore.utils.db.helpers import (
    _deactivate_processing_options,
    _get_dataset_by_name,
    _insert_dataset,
    _insert_dataset_resource,
    _insert_mappings,
    _insert_processing_option,
    _update_dataset,
    _update_dataset_from_resources,
)
from gqcore.utils.models import Dataset, DatasetResource, ProcessingOption


@logger.catch
def run_file_mask(fmask, fname):
    """extract temporal data from file name"""

    year = "".join([x for x, y in zip(fname, fmask) if y == "Y" and x.isdigit()])
    month = "".join([x for x, y in zip(fname, fmask) if y == "M" and x.isdigit()])
    day = "".join([x for x, y in zip(fname, fmask) if y == "D" and x.isdigit()])

    # check all potential issues
    if year == "":
        raise ValueError("No year found for data.")

    # full 4 digit year required
    elif len(year) != 4:
        raise ValueError("Invalid year.")

    # months must always use 2 digits
    elif month != "" and len(month) != 2:
        raise ValueError("Invalid month.")

    # days of month (day when month is given) must always use 2 digits
    elif month != "" and day != "" and len(day) != 2:
        raise ValueError("Invalid day of month.")

    # days of year (day when month is not given) must always use 3 digits
    elif month == "" and day != "" and len(day) != 3:
        raise ValueError("Invalid day of year.")

    # prepare timestamp
    if month == "" and day != "":
        date_str = f"{year}{day}"
        timestamp = datetime(year, 1, 1) + timedelta(day - 1)
    else:
        date_str = f"{year}{month}{day}"
        month = "01" if month == "" else month
        day = "01" if day == "" else day
        ymd = f"{year}{month}{day}"
        timestamp = datetime.strptime(ymd, "%Y%m%d")

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


@logger.catch
def get_raster_bbox(path):
    logger.debug("Retrieving bounds of raster at path {path}...")
    with rasterio.open(path, "r") as raster:
        # bounds = (xmin, ymin, xmax, ymax)
        b = raster.bounds
        logger.debug("Raster bounds are {repr(b)}")
        return box(*b)


@logger.catch
def insert_dataset(dataset: Dataset) -> None:
    params = dict(dataset)
    if params["mapped"]:
        params["mapped"] = params["mappings"] is not None

    params["other"] = Jsonb(params["other"])

    with get_conn() as conn:
        with conn.cursor() as cur:

            dataset_id = _insert_dataset(cur, params)

            if params["mapped"]:
                _insert_mappings(cur, dataset_id, params["mappings"])

            # if processing options were passed, insert those in the same transaction
            if params["processing_options"]:

                _deactivate_processing_options(cur, dataset_id)

                for processing_option in params["processing_options"]:
                    _insert_processing_option(cur, dataset_id, processing_option)

            dset_params = _identify_dataset_resources(
                cur,
                dataset_id,
                params["name"],
                params["file_mask"],
                params["file_extension"],
                params["path"],
            )

            _update_dataset_from_resources(cur, dataset_id, dset_params)

            conn.commit()


@logger.catch
def start_dataset_resources_check(name: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:

            dataset_info = _get_dataset_by_name(cur, name)

            dataset_id = dataset_info["id"]
            dataset_name = dataset_info["name"]
            file_mask = dataset_info["file_mask"]
            file_extension = dataset_info["file_extension"]
            dataset_path = Path(dataset_info["path"])

            dset_params = _identify_dataset_resources(
                cur, dataset_id, dataset_name, file_mask, file_extension, dataset_path
            )

            _update_dataset_from_resources(cur, dataset_id, dset_params)


@logger.catch
def _identify_dataset_resources(
    cur,
    dataset_id: int,
    dataset_name: str,
    file_mask: str,
    file_extension: str,
    dataset_path: Path,
) -> Dict[str, Any]:
    # dataset_path is read directly from an ingest json, so it won't actually be enforced as a Path yet
    dataset_path = Path(dataset_path)

    if not dataset_path.is_dir():
        file_list = [dataset_path]
    else:
        file_list = list(dataset_path.rglob("*" + file_extension))

    if file_mask is None and len(file_list) != 1:
        raise ValueError("Multiple files found, but no file mask specified")

    if not file_list:
        raise ValueError("No files found")

    # list of spatial extent bboxes for each resource that can be used to get total extent for dataset
    spatial_extent_bbox_list = []
    temporal_info_list = []
    # -------------------------------------
    # prepare resources

    resource_list = []

    for f in file_list:
        # path relative to base
        resource_path = os.path.relpath(f, dataset_path)

        spatial_extent_geom = get_raster_bbox(f)
        spatial_extent_bbox_list.append(spatial_extent_geom)
        resource_spatial_extent = spatial_extent_geom.wkt

        if file_mask is not None:
            # temporal
            # get unique time range based on dir path / file names

            # get data from mask
            timestamp, date_str, step, date_type = run_file_mask(
                file_mask, resource_path
            )
            temporal_info_list.append((timestamp, date_str, step, date_type))

            resource = DatasetResource(
                name=f"{dataset_name}_{date_str}",  # unique among this dataset's resources, not the same name as dataset
                path=resource_path,
                temporal=timestamp,
                label=date_str,
                spatial_extent=resource_spatial_extent,
            )

        else:
            resource = DatasetResource(
                name=f"{dataset_name}_none",
                path=resource_path,
                temporal=None,
                label=None,
                spatial_extent=resource_spatial_extent,
            )

        # update main list
        resource_list.append(resource)

    # -------------------------------------
    # get spatial and temporal for whole dataset

    if file_mask is None:
        temporal_name = "Temporally Invariant"
        temporal_start = None
        temporal_end = None
        temporal_type = None
    else:
        temporal_name = "Datetime"
        temporal_start = min([i[0] for i in temporal_info_list])
        temporal_end = max([i[0] for i in temporal_info_list])
        # temporal_step = min([i[2] for i in temporal_info_list])
        temporal_type = temporal_info_list[0][3]

    spatial_extent = shapely.ops.unary_union(spatial_extent_bbox_list).wkt

    dset_params = {
        "temporal_start": temporal_start,
        "temporal_end": temporal_end,
        "temporal_name": temporal_name,
        "temporal_type": temporal_type,
        "spatial_extent": spatial_extent,
    }

    # ==================

    if resource_list is not None:
        for resource in resource_list:
            _insert_dataset_resource(cur, dataset_id, resource)

    return dset_params


@logger.catch
def update_dataset(dataset: Dataset) -> None:
    params = dict(dataset)
    if params["mapped"]:
        params["mapped"] = params["mappings"] is not None

    params["other"] = Jsonb(params["other"])

    with get_conn() as conn:
        with conn.cursor() as cur:

            dataset_id = _update_dataset(cur, params)
            if dataset_id is None:
                raise ValueError("Dataset not found")

            if params["mapped"]:
                _insert_mappings(cur, dataset_id, params["mappings"])

            # if processing options were passed, insert those in the same transaction
            if params["processing_options"]:
                _deactivate_processing_options(cur, dataset_id)
                for processing_option in params["processing_options"]:
                    _insert_processing_option(cur, dataset_id, processing_option)

            dset_params = _identify_dataset_resources(
                cur,
                dataset_id,
                params["name"],
                params["file_mask"],
                params["file_extension"],
                params["path"],
            )

            _update_dataset_from_resources(cur, dataset_id, dset_params)

            conn.commit()
