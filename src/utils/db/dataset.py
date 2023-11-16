import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import utils.processors
from psycopg import Cursor
from psycopg.types.json import Json, Jsonb
from pydantic import BaseModel, Json, ValidationInfo, field_validator
from shapely.geometry.polygon import Polygon
from utils.conn import get_conn


class DatasetResource(BaseModel):
    name: str
    path: Path
    temporal_start: Optional[datetime]
    temporal_end: Optional[datetime]
    spatial_extent: Optional[Polygon]
    size_kb: int
    other: Jsonb


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
    def validate_path(cls, f: str, info: ValidationInfo) -> str:
        f = str(f)
        if f.endswith("/"):
            Warning("path must not end with a slash, correcting for you")
            f = f[:-1]
        return f

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
            size_kb,
            other
        ) VALUES (
            %(dataset_id)s,
            %(name)s,
            %(path)s,
            %(temporal_start)s,
            %(temporal_end)s,
            %(spatial_extent)s,
            %(size_kb)s,
            %(other)s
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


def insert_dataset(
    dataset: Dataset, dataset_resources: Optional[List[DatasetResource]] = None
) -> None:
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

            if dataset_resources is not None:
                for resource in dataset_resources:
                    _insert_dataset_resource(cur, dataset_id, resource)

            conn.commit()


def update_dataset(dataset: Dataset) -> None:
    params = dict(dataset)
    if params["mapped"]:
        bool = params["mappings"] is not None

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
