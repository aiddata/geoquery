import calendar
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import rasterio
import shapely
import utils.processors
from dateutil.relativedelta import relativedelta
from psycopg import Cursor
from psycopg.types.json import Json, Jsonb
from pydantic import BaseModel, Json, ValidationInfo, field_validator
from shapely.geometry import box
from shapely.geometry.polygon import Polygon

from utils.db.conn import get_conn


def run_file_mask(fmask, fname):
    """extract temporal data from file name"""

    year = "".join([x for x, y in zip(fname, fmask) if y == "Y" and x.isdigit()])
    month = "".join([x for x, y in zip(fname, fmask) if y == "M" and x.isdigit()])
    day = "".join([x for x, y in zip(fname, fmask) if y == "D" and x.isdigit()])

    # check all potential issues
    if year == "":
        raise Exception("No year found for data.")

    # full 4 digit year required
    elif len(year) != 4:
        raise Exception("Invalid year.")

    # months must always use 2 digits
    elif month != "" and len(month) != 2:
        raise Exception("Invalid month.")

    # days of month (day when month is given) must always use 2 digits
    elif month != "" and day != "" and len(day) != 2:
        raise Exception("Invalid day of month.")

    # days of year (day when month is not given) must always use 3 digits
    elif month == "" and day != "" and len(day) != 3:
        raise Exception("Invalid day of year.")

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


def get_raster_bbox(path):
    with rasterio.open(path, "r") as raster:
        # bounds = (xmin, ymin, xmax, ymax)
        b = raster.bounds
        return box(*b)


class DatasetResource(BaseModel):
    name: str
    path: str
    temporal: Optional[datetime]
    label: Optional[str]
    spatial_extent: Optional[str]


class ProcessingOption(BaseModel):
    dataset_id: int = None # this needs to be None in the model because dataset id is not known at the time of validation
    active: bool = False
    public: bool = False
    short_name: str
    function: str
    kwargs: dict

    @field_validator("function")
    @classmethod
    def validate_function(cls, f: str) -> str:
        if not hasattr(utils.processors, f) and callable(getattr(utils.processors, f)):
            raise ValueError(
                "function must be a callable from the utils.processors module"
            )
        return f


class Dataset(BaseModel):
    active: bool = False
    public: bool = False
    mapped: bool = False
    mappings: Optional[Dict[str, int]] = None  # categorial data mappings
    name: str
    type: str
    path: Path
    file_extension: str
    file_mask: str
    title: str
    description: str
    details: str
    tags: Optional[List[str]] = None
    citation: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    variable_description: Optional[str] = None
    variable_factor: Optional[float] = None
    processing_options: Optional[List[ProcessingOption]] = None
    other: Optional[dict] = None
    temporal_start: Optional[datetime] = None
    temporal_end: Optional[datetime] = None
    temporal_name: Optional[str] = None
    temporal_type: Optional[str] = None
    is_global: bool
    coverage_dependency: Optional[str] = None
    ingest_src: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, f: str, info: ValidationInfo) -> str:
        if f != f.lower():
            raise ValueError("name must be lowercase")

        if f != re.sub(" ", "_", f):
            raise ValueError("name must not have spaces")

        if f != re.sub("[^0-9a-zA-Z._-]+", "", f):
            raise ValueError(
                "name must be alphanumeric with only underscores, dashes, or periods"
            )
        return f

    @field_validator("path")
    @classmethod
    def validate_path(cls, fp: str, info: ValidationInfo) -> str:
        if not Path(fp).exists():
            raise ValueError("path must exist")
        fs = str(fp)
        if fs.endswith("/"):
            Warning("path must not end with a slash, correcting for you")
            fs = fs[:-1]
        return fs

    # @field_validator("name")
    # @classmethod
    # def name_is_unique(cls, f: str, info: ValidationInfo) -> str:
    #     with get_conn() as conn:
    #         with conn.cursor() as cur:
    #             if not info["update_meta"]:
    #                 query = "SELECT * FROM datasets WHERE name = %s;", (f,)
    #                 result = cur.execute(query)
    #                 if result:
    #                     raise ValueError("name not unique")
    #             else:
    #                 query = "SELECT * FROM datasets WHERE name = %s;", (f,)
    #                 result = cur.execute(query)
    #                 if not result:
    #                     raise ValueError("existing dataset not found")
    #     return f


def _insert_mappings(cur: Cursor, dataset_id: int, mappings: Dict[str, int]) -> None:
    cur.execute("DELETE FROM mappings WHERE dataset_id = %s ;", (dataset_id,))

    for key, value in mappings.items():
        cur.execute(
            """
            INSERT INTO mappings (
                dataset_id,
                map_name,
                map_val
            ) VALUES (
                %s,
                %s,
                %s
            )
            """,
            (dataset_id, key, value),
        )


def _insert_dataset_resource(cur: Cursor, dataset_id: int, resource: DatasetResource):
    query = """
        INSERT INTO dataset_resources (
            dataset_id,
            name,
            path,
            temporal,
            label,
            spatial_extent
        ) VALUES (
            %(dataset_id)s,
            %(name)s,
            %(path)s,
            %(temporal)s,
            %(label)s,
            %(spatial_extent)s
        )
        ON CONFLICT (name)
        DO UPDATE SET (path, temporal, label, spatial_extent) = (%(path)s, %(temporal)s, %(label)s, %(spatial_extent)s)
        ;
    """

    params = dict(resource)
    params.update({"dataset_id": dataset_id})

    cur.execute(query, params)


def insert_dataset_resource(cur, dataset_id: int, resource: DatasetResource):
    with get_conn() as conn:
        with conn.cursor() as cur:
            _insert_dataset_resource(cur, dataset_id, resource)


def _insert_processing_option(
    cur: Cursor, dataset_id: int, processing_option: ProcessingOption
) -> None:
    query = """
        INSERT INTO processing_options (
            dataset_id,
            active,
            public,
            short_name,
            function,
            kwargs
        ) VALUES (
            %(dataset_id)s,
            %(active)s,
            %(public)s,
            %(short_name)s,
            %(function)s,
            %(kwargs)s
        )
        ON CONFLICT (dataset_id, function, kwargs)
        DO UPDATE SET (active, public, short_name) = (%(active)s, %(public)s, %(short_name)s)
        ;
    """
    params = processing_option.dict()
    params.update({"dataset_id": dataset_id})
    params["kwargs"] = Jsonb(params["kwargs"])
    cur.execute(query, params)


def insert_dataset(dataset: Dataset) -> None:
    params = dict(dataset)
    if params["mapped"]:
        params["mapped"] = params["mappings"] is not None

    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                INSERT INTO datasets (
                    active,
                    public,
                    mapped,
                    name,
                    type,
                    path,
                    file_extension,
                    file_mask,
                    title,
                    description,
                    details,
                    tags,
                    citation,
                    source_name,
                    source_url,
                    variable_description,
                    variable_factor,
                    other,
                    temporal_start,
                    temporal_end,
                    temporal_name,
                    temporal_type,
                    ingest_src
                ) VALUES (
                    %(active)s,
                    %(public)s,
                    %(mapped)s,
                    %(name)s,
                    %(type)s,
                    %(path)s,
                    %(file_extension)s,
                    %(file_mask)s,
                    %(title)s,
                    %(description)s,
                    %(details)s,
                    %(tags)s,
                    %(citation)s,
                    %(source_name)s,
                    %(source_url)s,
                    %(variable_description)s,
                    %(variable_factor)s,
                    %(other)s,
                    %(temporal_start)s,
                    %(temporal_end)s,
                    %(temporal_name)s,
                    %(temporal_type)s,
                    %(ingest_src)s
                ) RETURNING id;
            """
            params["other"] = Jsonb(params["other"])

            cur.execute(query, params)

            dataset_id = cur.fetchone()["id"]

            if params["mapped"]:
                _insert_mappings(cur, dataset_id, params["mappings"])

            # if processing options were passed, insert those in the same transaction
            if params["processing_options"]:
                cur.execute(
                    "UPDATE processing_options SET active = False WHERE dataset_id = %s ;",
                    (dataset_id,),
                )
                for processing_option in params["processing_options"]:
                    _insert_processing_option(cur, dataset_id, processing_option)

            dset_params = identify_dataset_resources(
                cur,
                dataset_id,
                params["name"],
                params["file_mask"],
                params["file_extension"],
                params["path"],
            )

            update_dataset_from_resources(cur, dataset_id, dset_params)

            conn.commit()


def update_dataset_from_resources(cur, dataset_id: int, dset_params: dict) -> None:
    dset_params["dataset_id"] = dataset_id
    cur.execute(
        """
        UPDATE datasets SET (
            temporal_start,
            temporal_end,
            temporal_name,
            temporal_type,
            spatial_extent
        ) = (
            %(temporal_start)s,
            %(temporal_end)s,
            %(temporal_name)s,
            %(temporal_type)s,
            %(spatial_extent)s
        ) WHERE id = %(dataset_id)s
    """,
        dset_params,
    )


def start_dataset_resources_check(dataset_name: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM datasets WHERE name = %s ;", (dataset_name,))

            dataset_info = cur.fetchone()

            dataset_id = dataset_info["id"]
            dataset_name = dataset_info["name"]
            file_mask = dataset_info["file_mask"]
            file_extension = dataset_info["file_extension"]
            dataset_path = Path(dataset_info["path"])

            dset_params = identify_dataset_resources(
                cur, dataset_id, dataset_name, file_mask, file_extension, dataset_path
            )

            update_dataset_from_resources(cur, dataset_id, dset_params)


def identify_dataset_resources(
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

    # list of spatial exten bboxes for each resource that can be used to get total extent for dataset
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


def update_dataset(dataset: Dataset) -> None:
    params = dict(dataset)
    if params["mapped"]:
        params["mapped"] = params["mappings"] is not None

    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                UPDATE datasets SET (
                    active,
                    public,
                    mapped,
                    name,
                    type,
                    path,
                    file_extension,
                    file_mask,
                    title,
                    description,
                    details,
                    tags,
                    citation,
                    source_name,
                    source_url,
                    variable_description,
                    variable_factor,
                    other,
                    temporal_start,
                    temporal_end,
                    temporal_name,
                    temporal_type,
                    ingest_src
                ) = (
                    %(active)s,
                    %(public)s,
                    %(mapped)s,
                    %(name)s,
                    %(type)s,
                    %(path)s,
                    %(file_extension)s,
                    %(file_mask)s,
                    %(title)s,
                    %(description)s,
                    %(details)s,
                    %(tags)s,
                    %(citation)s,
                    %(source_name)s,
                    %(source_url)s,
                    %(variable_description)s,
                    %(variable_factor)s,
                    %(other)s,
                    %(temporal_start)s,
                    %(temporal_end)s,
                    %(temporal_name)s,
                    %(temporal_type)s,
                    %(ingest_src)s
                ) WHERE name = %(name)s
                RETURNING id;
            """
            params["other"] = Jsonb(params["other"])

            cur.execute(query, params)

            dataset_id = cur.fetchone()["id"]

            if params["mapped"]:
                _insert_mappings(cur, dataset_id, params["mappings"])

            # if processing options were passed, insert those in the same transaction
            if params["processing_options"]:
                cur.execute(
                    "UPDATE processing_options SET active = False WHERE dataset_id = %s ;",
                    (dataset_id,),
                )
                for processing_option in params["processing_options"]:
                    _insert_processing_option(cur, dataset_id, processing_option)

            dset_params = identify_dataset_resources(
                cur,
                dataset_id,
                params["name"],
                params["file_mask"],
                params["file_extension"],
                params["path"],
            )

            update_dataset_from_resources(cur, dataset_id, dset_params)

            conn.commit()
