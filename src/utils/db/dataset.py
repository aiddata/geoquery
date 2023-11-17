import re
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import utils.processors
from psycopg import Cursor
from psycopg.types.json import Json, Jsonb
from pydantic import BaseModel, Json, ValidationInfo, field_validator
from shapely.geometry.polygon import Polygon
from utils.conn import get_conn


import calendar
from dateutil.relativedelta import relativedelta

import rasterio
from shapely.geometry import box

def run_file_mask(fmask, fname):
    """extract temporal data from file name
    """
    output = {
        "year": "".join([x for x,y in zip(fname, fmask) if y == 'Y' and x.isdigit()]),
        "month": "".join([x for x,y in zip(fname, fmask) if y == 'M' and x.isdigit()]),
        "day": "".join([x for x,y in zip(fname, fmask) if y == 'D' and x.isdigit()])
    }
    return output


def validate_date(date_obj):
    """validate a date object
    """
    # year is always required
    y = date_obj["year"]
    m = date_obj["month"]
    d = date_obj["day"]

    if y == "":
        return False, "No year found for data."

    # full 4 digit year required
    elif len(y) != 4:
        return False, "Invalid year."

    # months must always use 2 digits
    elif m != "" and len(m) != 2:
        return False, "Invalid month."

    # days of month (day when month is given) must always use 2 digits
    elif m != "" and d != "" and len(d) != 2:
        return False, "Invalid day of month."

    # days of year (day when month is not given) must always use 3 digits
    elif m == "" and d != "" and len(d) != 3:
        return False, "Invalid day of year."

    return True, None


# generate date range and date type from date object
def get_date_range(date_obj, drange=0):
    y = date_obj["year"]
    m = date_obj["month"]
    d = date_obj["day"]

    date_type = "None"

    # year, day of year (7)
    if m == "" and len(d) == 3:
        tmp_start = datetime(int(y), 1, 1) + datetime.timedelta(int(d)-1)
        tmp_end = tmp_start + relativedelta(days=drange)
        date_type = "day of year"

    # year, month, day (8)
    if m != "" and len(d) == 2:
        tmp_start = datetime(int(y), int(m), int(d))
        tmp_end = tmp_start + relativedelta(days=drange)
        date_type = "year month day"

    # year, month (6)
    if m != "" and d == "":
        tmp_start = datetime(int(y), int(m), 1)
        month_range = calendar.monthrange(int(y), int(m))[1]
        tmp_end = datetime(int(y), int(m), month_range)
        date_type = "year month"

    # year (4)
    if m == "" and d == "":
        tmp_start = datetime(int(y), 1, 1)
        tmp_end = datetime(int(y), 12, 31)
        date_type = "year"

    return (int(datetime.strftime(tmp_start, '%Y%m%d')),
            int(datetime.strftime(tmp_end, '%Y%m%d')),
            date_type)


def get_raster_extent(path):
    """Get geojson style envelope of raster file
    """
    with rasterio.open(path, 'r') as raster:

        # bounds = (xmin, ymin, xmax, ymax)
        b = raster.bounds
        env = [[b[0], b[3]], [b[0], b[1]], [b[2], b[1]], [b[2], b[3]]]

        return env


def trim_envelope(env):
    """Trim envelope to global extents
    """
    # clip extents if they are outside global bounding box
    for c in range(len(env)):
        if env[c][0] < -180:
            env[c][0] = -180

        elif env[c][0] > 180:
            env[c][0] = 180

        if env[c][1] < -90:
            env[c][1] = -90

        elif env[c][1] > 90:
            env[c][1] = 90

    return env


def envelope_to_geom(env):
    """convert envelope array to geojson
    """
    geom = {
        "type": "Polygon",
        "coordinates": [ [
            env[0],
            env[1],
            env[2],
            env[3],
            env[0]
        ] ]
    }
    return geom

class DatasetResource(BaseModel):
    name: str
    path: str
    temporal_start: Optional[datetime]
    temporal_end: Optional[datetime]
    spatial_extent: Optional[str]


class ProcessingOption(BaseModel):
    dataset_id: int = None
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
    temporal_step: Optional[timedelta] = None
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
            temporal_start,
            temporal_end,
            spatial_extent,
        ) VALUES (
            %(dataset_id)s,
            %(name)s,
            %(path)s,
            %(temporal_start)s,
            %(temporal_end)s,
            %(spatial_extent)s,
        );
    """

    params = dict(resource)
    params.update({"dataset_id": dataset_id})

    cur.execute(query, params)


def insert_dataset_resource(dataset_id: int, resource: DatasetResource):
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
                    temporal_step,
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
                    %(temporal_step)s,
                    %(ingest_src)s
                ) RETURNING id;
            """
            params["other"] = Jsonb(params["other"])

            cur.execute(query, params)

            dataset_id = cur.fetchone()[0]

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

            identify_dataset_resources(dataset_id, params["name"], params["file_mask"], params["file_extension"], params["path"])

            conn.commit()



def start_dataset_resources_check(dataset_name: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM datasets WHERE name = %s ;", (dataset_name,))

            dataset_info = cur.fetchone()[0]

            dataset_id = dataset_info["id"]
            dataset_name = dataset_info["name"]
            file_mask = dataset_info["file_mask"]
            file_extension = dataset_info["file_extension"]
            dataset_path = Path(dataset_info["path"])

            identify_dataset_resources(dataset_id, dataset_name, file_mask, file_extension, dataset_path)


def identify_dataset_resources(dataset_id: int, dataset_name:str, file_mask: str, file_extension: str, dataset_path: str) -> None:

    dataset_path = Path(dataset_path)

    if not dataset_path.is_dir():
        file_list = [dataset_path]
    else:
        file_list = list(dataset_path.rglob("*" + file_extension))

    if file_mask is None and len(file_list) != 1:
        raise ValueError("Multiple files found, but no file mask specified")

    # -------------------------------------
    # check file mask

    # file mask identifying temporal attributes in path/file names
    test_fname = os.path.relpath(file_list[0], dataset_path)
    test_date_str = run_file_mask(file_mask, test_fname)
    valid_date = validate_date(test_date_str)
    if not valid_date:
        raise ValueError("File mask failed to validate using first resource ({}).".format(test_fname))


    # -------------------------------------
    # prepare resources

    resource_list = []

    for f in file_list:
        print(f)
        # individual resource info
        resource = {}

        # path relative to base
        resource["path"] = os.path.relpath(f, dataset_path)

        resource["spatial"] = get_raster_extent(f)

        if file_mask is not None:
            # temporal
            # get unique time range based on dir path / file names

            # get data from mask
            date_str = run_file_mask(file_mask, resource["path"])
            validate_date_str = validate_date(date_str)
            if not validate_date_str[0]:
                raise Exception(validate_date_str[1])

            # if "day_range" in doc:
            #     resource["start"], resource["end"], range_type = get_date_range(date_str, doc["day_range"])
            # else:
            resource["start"], resource["end"], range_type = get_date_range(date_str)

            # name (unique among this dataset's resources,
            # not same name as dataset name)
            resource["name"] = f"{dataset_name}_{date_str['year']}{date_str['month']}{date_str['day']}"

        else:
            resource["start"]  = 10000101
            resource["end"] = 99991231
            resource["name"] = f"{dataset_name}_none"


        # update main list
        resource_list.append(resource)

    breakpoint()

    # -------------------------------------
    # get temporal for whole dataset

    if file_mask is None:
        temporal_name = "Temporally Invariant"
        temporal_format = None
        temporal_type = None
    else:
        temporal_name = "Date Range"
        temporal_format = "%Y%m%d"
        temporal_type = get_date_range(run_file_mask(file_mask, file_list[0].name))[2]


    temporal_start = None
    temporal_end = None
    for r in resource_list:
        if (temporal_start is None or
                r["start"] < temporal_start):
            temporal_start = r["start"]
        elif (temporal_end is None or
                r["end"] > temporal_end):
            temporal_end = r["end"]


    # -------------------------------------
    # get spatial for full dataset

    # iterate over files to get bbox and do basic spatial validation
    # (mainly make sure rasters are all same size)
    base_geo = None
    for f in file_list:
        # get basic geo info from each file
        env = get_raster_extent(f)
        # get full geo info from first file
        base_geo = env if not base_geo else base_geo
        if base_geo != env:
            Warning(f"Raster bounding box does not match: \n\tfile: {f}\n\tbbox: {env}\n\tbase: {base_geo}")


    env = trim_envelope(env)
    print("Dataset bounding box: ", env)

    # set spatial
    spatial_extent = envelope_to_geom(env)


    # ==================

    resource_list = []

    if resource_list is not None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for resource in resource_list:
                    _insert_dataset_resource(cur, dataset_id, resource)



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
                    temporal_step,
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
                    %(temporal_step)s,
                    %(ingest_src)s
                ) WHERE name = %(name)s
                RETURNING id;
            """
            params["other"] = Jsonb(params["other"])

            cur.execute(query, params)

            dataset_id = cur.fetchone()[0]

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

            conn.commit()
