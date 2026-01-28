import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import shapely
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ValidationInfo, field_validator
from shapely import Polygon

import gqcore.utils.processors


class BaseModel(PydanticBaseModel):
    class Config:
        arbitrary_types_allowed = True


class Feature(BaseModel):
    """
    An individual feature, as selected from the database.
    """

    geometry: str  # this is a wkt str. TODO: this does not include CRS info. We should verify (or be reasonably certain) it is EPSG:4326
    name: Optional[str]
    attr: Optional[dict]
    parent: Optional[int]

    @field_validator("geometry")
    @classmethod
    def validate_geometry(cls, g: str) -> str:
        geom = shapely.wkt.loads(g)
        if not geom.is_valid:
            raise ValueError("the geometry of a feature must be well-formed.")
        return g


class IngestFeatureCollection(BaseModel):
    """
    A feature collection, along with all of its features, ready to be ingested into the system.
    Does not include an ID, as those are assigned by the database.
    """

    active: bool = False
    public: bool = False
    name: str
    path: str
    file_extension: str
    file_mask: Optional[str] = None
    title: str
    description: str
    details: Optional[str] = None
    tags: List[str]
    citation: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    other: Optional[dict] = None
    temporal_start: Optional[datetime] = None
    temporal_end: Optional[datetime] = None
    temporal_name: Optional[str] = None
    temporal_type: Optional[str] = None
    spatial_extent: str
    is_global: bool
    ingest_src: Optional[str] = None
    group_name: Optional[str] = None
    group_title: Optional[str] = None
    group_class: Optional[str] = None
    group_level: Optional[int] = None
    features: List[Feature]


class FeatureCollection(BaseModel):
    """
    A feature collection as stored by (and selected from) the database.
    """

    id: int
    active: bool = False
    public: bool = False
    name: str
    path: str
    file_extension: str
    file_mask: Optional[str] = None
    title: str
    description: str
    details: Optional[str] = None
    tags: List[str]
    citation: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    other: Optional[dict] = None
    temporal_start: Optional[datetime] = None
    temporal_end: Optional[datetime] = None
    temporal_name: Optional[str] = None
    temporal_type: Optional[str] = None
    spatial_extent: Polygon
    is_global: bool
    ingest_src: Optional[str] = None
    group_name: Optional[str] = None
    group_title: Optional[str] = None
    group_class: Optional[str] = None
    group_level: Optional[int] = None


class DatasetResource(BaseModel):
    name: str
    path: str
    temporal: Optional[datetime]
    label: Optional[str]
    spatial_extent: Optional[str]


class ProcessingOption(BaseModel):
    dataset_id: int = None  # this needs to be None in the model because dataset id is not known at the time of validation
    active: bool = False
    public: bool = False
    short_name: str
    function: str
    result_type: str
    kwargs: dict

    @field_validator("function")
    @classmethod
    def validate_function(cls, f: str) -> str:
        if not hasattr(gqcore.utils.processors, f) and callable(
            getattr(gqcore.utils.processors, f)
        ):
            raise ValueError(
                "function must be a callable from the gqcore.utils.processors module"
            )
        return f

    @field_validator("result_type")
    @classmethod
    def validate_result_type(cls, s: str) -> str:
        valid_result_types = ["float", "int", "str"]
        if s not in valid_result_types:
            raise ValueError(
                "result_types must be one of the following: {}".format(
                    valid_result_types
                )
            )
        return s


class Dataset(BaseModel):
    active: bool = False
    public: bool = False
    name: str
    path: Path
    file_extension: str
    file_mask: Optional[str]
    title: str
    description: str
    details: str
    tags: Optional[List[str]] = None
    citation: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    other: Optional[dict] = None
    temporal_start: Optional[datetime] = None
    temporal_end: Optional[datetime] = None
    temporal_name: Optional[str] = None
    temporal_type: Optional[str] = None
    is_global: bool
    ingest_src: Optional[str] = None
    mapped: bool = False
    mappings: Optional[Dict[str, int]] = None  # categorial data mappings
    type: str
    variable_description: Optional[str] = None
    variable_factor: Optional[float] = None
    processing_options: Optional[List[ProcessingOption]] = None
    coverage_dependency: Optional[str] = None

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


extract_task_valid_status_dict = {
    -1: "error",
    0: "not started",
    1: "complete",
    2: "started",
}


class ExtractTask(BaseModel):
    resource_id: int
    fm_id: int
    po_id: int
    status: Optional[int]
    priority: Optional[int]
    submit_time: Optional[datetime] = datetime.now()
    # start_time: Optional[datetime]
    # update_time: Optional[datetime]
    # complete_time: Optional[datetime]
    # attempts: Optional[int]
    # error: Optional[str]
    kwargs: Optional[dict] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, s: int) -> int:
        if s not in extract_task_valid_status_dict:
            raise ValueError(
                "status must be one of the following: {}".format(
                    extract_task_valid_status_dict
                )
            )
        return s


coverage_record_valid_status_dict = {
    -1: "not checked",
    0: "no coverage",
    1: "coverage",
}


class CoverageRecord(BaseModel):
    geom_id: int
    dataset_id: int
    status: Optional[int] = -1

    @field_validator("status")
    @classmethod
    def validate_statusn(cls, s: int) -> int:
        if s not in coverage_record_valid_status_dict:
            raise ValueError(
                "status must be one of the following: {}".format(
                    coverage_record_valid_status_dict
                )
            )
        return s
