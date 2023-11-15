from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import re

from psycopg import Cursor
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Json, field_validator, ValidationInfo

import processors
from conn import get_conn
from resource_management import populate_resources


class ProcessingOption(BaseModel):
    dataset_id: int
    active: bool = False
    public: bool = False
    short_name: str
    function: str
    kwargs: Json

    @field_validator("function")
    @classmethod
    def function_must_exist(cls, f: str) -> str:
        if not hasattr(processors, f):
            raise ValueError("function must be a callable from the processors module")
        return f


class Dataset(BaseModel):
    update_meta: bool = False
    update_resources: bool = False
    active: bool = False
    public: bool = False
    mappings: Optional[Dict[str, int]] = None  # categorial data mappings
    name: str
    type: str
    path: Path
    file_extension: str
    file_mask: str
    title: str
    description: str
    details: str
    version: str
    tags: Optional[List[str]] = None
    citation: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    variable_description: Optional[str] = None
    variable_factor: Optional[float] = None
    processing_options: Optional[Json] = None
    other: Optional[Json] = None
    temporal_start: Optional[datetime] = None
    temporal_end: Optional[datetime] = None
    temporal_step: Optional[timedelta] = None
    is_global: bool
    coverage_dependency: Optional[str] = None
    ingest_src: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_is_unique(cls, f: str, info: ValidationInfo) -> str:
        if f != f.lower():
            raise ValueError("name must be lowercase")

        clean = re.sub(' ', '_', f)
        clean = re.sub('[^0-9a-zA-Z._-]+', '', clean)

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
            );
        """,
            (dataset_id, key, value),
        )


def add_processing_option(dataset_id: int, processing_option: ProcessingOption) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
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
                );
            """

            cur.execute(query, processing_option)


def insert_dataset(dataset: Dataset) -> None:
    params = dict(dataset)
    if params["mapped"]:
        bool = params["mappings"] is not None

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
                    version,
                    tags,
                    citation,
                    source_name,
                    source_url,
                    variable_description,
                    variable_factor,
                    processing_options,
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
                    %(version)s,
                    %(tags)s,
                    %(citation)s,
                    %(source_name)s,
                    %(source_url)s,
                    %(variable_description)s,
                    %(variable_factor)s,
                    %(processing_options)s,
                    %(other)s,
                    %(temporal_start)s,
                    %(temporal_end)s,
                    %(ingest_src)s
                ) RETURNING id;
            """

            cur.execute(query, params)

            dataset_id = cur.fetchone()[0]

            if params["mapped"]:
                _insert_mappings(cur, dataset_id, params["mappings"])

            cur.commit()

            populate_resources(dataset_id)
