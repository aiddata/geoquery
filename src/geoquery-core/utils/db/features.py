from typing import List

from psycopg import Cursor
from psycopg.types.json import Jsonb

from utils.db.conn import get_conn
from utils.models import Feature, FeatureCollection


def insert_feature_collection(feature_collection: FeatureCollection) -> None:

    fc_params = feature_collection.dict()
    fc_params["other"] = Jsonb(fc_params["other"])

    with get_conn() as conn:
        with conn.cursor() as cur:
            feature_collection_id = _insert_feature_collection(cur, fc_params)
            for feature in feature_collection.features:
                _insert_feature(cur, feature_collection_id, feature)

def update_feature_collection(feature_collection: FeatureCollection) -> None:

    fc_params = feature_collection.dict()
    fc_params["other"] = Jsonb(fc_params["other"])

    with get_conn() as conn:
        with conn.cursor() as cur:
            feature_collection_id = _update_feature_collection(cur, fc_params)
            if feature_collection_id is None:
                raise ValueError("No feature collection found with that name")
            for feature in feature_collection.features:
                _insert_feature(cur, feature_collection_id, feature)


def _update_feature_collection(cur: Cursor, params: dict) -> int:

    query = """
        UPDATE feature_collections SET
            active = %(active)s,
            public = %(public)s,
            name = %(name)s,
            path = %(path)s,
            file_extension = %(file_extension)s,
            title = %(title)s,
            description = %(description)s,
            details = %(details)s,
            tags = %(tags)s,
            citation = %(citation)s,
            source_name = %(source_name)s,
            source_url = %(source_url)s,
            other = %(other)s,
            temporal_start = %(temporal_start)s,
            temporal_end = %(temporal_end)s,
            temporal_step = %(temporal_step)s,
            spatial_extent = %(spatial_extent)s,
            is_global = %(is_global)s,
            ingest_src = %(ingest_src)s,
            group_name = %(group_name)s,
            group_title = %(group_title)s,
            group_class = %(group_class)s,
            group_level = %(group_level)s
        WHERE name = %(name)s
        RETURNING id;
    """

    cur.execute(query, params)
    result = cur.fetchone()
    if result is None:
        feature_collection_id = None
    else:
        feature_collection_id = result["id"]
    return feature_collection_id


def _insert_feature_collection(cur: Cursor, params: dict) -> int:

    query = """
        INSERT INTO feature_collections (
            active,
            public,
            name,
            path,
            file_extension,
            title,
            description,
            details,
            tags,
            citation,
            source_name,
            source_url,
            other,
            temporal_start,
            temporal_end,
            temporal_step,
            spatial_extent,
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
            %(path)s,
            %(file_extension)s,
            %(title)s,
            %(description)s,
            %(details)s,
            %(tags)s,
            %(citation)s,
            %(source_name)s,
            %(source_url)s,
            %(other)s,
            %(temporal_start)s,
            %(temporal_end)s,
            %(temporal_step)s,
            %(spatial_extent)s,
            %(is_global)s,
            %(ingest_src)s,
            %(group_name)s,
            %(group_title)s,
            %(group_class)s,
            %(group_level)s
        ) RETURNING id;
    """

    cur.execute(query, params)
    feature_collection_id = cur.fetchone()["id"]
    return feature_collection_id


def _insert_feature(cur: Cursor, feature_collection_id: int, feature: Feature) -> None:
    wkt = feature.geometry

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
        result = cur.fetchone()["id"]
    else:
        # print("Found a matching geometry!")
        result = result["id"]

    fm_params = {
        "fc_id": feature_collection_id,
        "geom_id": result,
        "name": feature.name,
        "attr": Jsonb(feature.attr),
        "parent": None,
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
        )
        ON CONFLICT (fc_id, geom_id) DO UPDATE SET
            name = %(name)s,
            attr = %(attr)s,
            parent = %(parent)s
        """,
        fm_params,
    )
