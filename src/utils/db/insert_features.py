from datetime import datetime, timedelta
from typing import List, Optional

import shapely
from psycopg import Cursor
from pydantic import BaseModel, Json, field_validator
from shapely.geometry.polygon import Polygon

from utils.conn import get_conn


class Feature(BaseModel):
    geometry: List[
        Polygon
    ]  # TODO: I don't think this includes CRS info? We'll have to deal with that
    name: Optional[str]
    attr: Json
    parent: Optional[int]

    @field_validator("geometry")
    @classmethod
    def function_must_exist(cls, g: str) -> str:
        if not shapely.is_valid(g):
            raise ValueError("the geometry of a feature must be well-formed.")
        return g


class FeatureCollection(BaseModel):
    features: List[Feature]
    active: bool = False
    public: bool = False
    name: str
    type: str
    path: str
    file_extension: str
    file_mask: str
    title: str
    description: str
    details: str
    tags: List[str]
    citation: Optional[str] = None
    source_name: Optional[str] = None
    source_link: Optional[str] = None
    other: Optional[Json] = None
    temporal_start: Optional[datetime] = None
    temporal_end: Optional[datetime] = None
    temporal_step: Optional[timedelta] = None
    is_global: bool
    ingest_src: Optional[str] = None
    group_name: Optional[str] = None
    group_title: Optional[str] = None
    group_class: Optional[str] = None
    group_level: Optional[int] = None


def _insert_features(
    cur: Cursor, feature_collection_id: int, features: List[Feature]
) -> None:
    for feature in features:
        wkt = shapely.to_wkt(feature.geometry)

        # check if geom is already in features table, returning any matching ids
        cur.execute(
            """
            SELECT id FROM features WHERE ST_Equals(ST_GeomFromText(%s), shape)
        """,
            (wkt,),
        )

        result = cur.fetchone()

        if result is None:
            cur.execute(
                """
                INSERT INTO features (shape) VALUES (ST_GeomFromText(%s)) RETURNING id;
                """,
                (wkt,),
            )
            result = cur.fetchone()[0]
        else:
            # print("Found a matching geometry!")
            result = result[0]

        added_params = {
            "fc_id": feature_collection_id,
            "geom_id": result,
        }

        # insert into feat_map with that id
        cur.execute(
            """
            INSERT INTO feat_map (
                fc_id,
                geom_id,
                name,
                attr,
                parent
            ) VALUES (
                %(fc_id)s,
                %(geom_id)s,
                %(name)s,
                %(attr)s,
                %(parent)s
            );
            """,
            dict(feature).update(added_params),
        )


def insert_feature_collection(feature_collection: FeatureCollection) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                INSERT INTO feature_collections (
                    active,
                    public,
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
                    source_link,
                    other,
                    temporal_start,
                    temporal_end,
                    temporal_step,
                    is_global,
                    ingest_src,
                    group_name,
                    group_title,
                    group_class,
                    group_level
                ) VALUES (
                    %(active)s,
                    %(public)s,
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
                    %(source_link)s,
                    %(variable_description)s,
                    %(variable_factor)s,
                    %(processing_options)s,
                    %(other)s,
                    %(temporal_start)s,
                    %(temporal_end)s,
                    %(temporal_step)s,
                    %(spatial)s,
                    %(is_global)s,
                    %(ingest_src)s,
                    %(group_name)s,
                    %(group_title)s,
                    %(group_class)s,
                    %(group_level)s
                ) RETURNING id;
            """

            cur.execute(query, feature_collection)

            feature_collection_id = cur.fetchone()[0]

            _insert_features(cur, feature_collection_id, feature_collection.features)
