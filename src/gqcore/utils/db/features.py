
from psycopg import Cursor
from psycopg.types.json import Jsonb
from loguru import logger

from gqcore.utils.db.conn import get_conn
from gqcore.utils.models import Feature, FeatureCollection


@logger.catch(reraise=False)
def insert_feature_collection(
        feature_collection: FeatureCollection,
        skip_existing:bool=False,
        update_meta:bool=False,
        replace_features:bool=False,
        update_features:bool=False,
    ) -> None:

    fc_params = feature_collection.dict()
    fc_params["other"] = Jsonb(fc_params["other"])

    if replace_features or update_features:
        if not update_meta:
            logger.warning("update_meta will be set to True if replace_features or update_features is True")
            update_meta = True

    with get_conn() as conn:
        with conn.cursor() as cur:

            feature_collection_id = None

            if skip_existing:
                feature_collection_id = _get_feature_collection_id(cur, fc_params["name"])
                if feature_collection_id:
                    logger.info(f"Skipping feature collection {fc_params['name']} because it already exists")
                    return

            if update_meta:
                feature_collection_id = _update_feature_collection(cur, fc_params)
                if not feature_collection_id:
                    raise ValueError("No feature collection found with that name")
            else:
                feature_collection_id = _insert_feature_collection(cur, fc_params)

            if replace_features:
                # delete all features associated with this feature collection
                cur.execute(
                    """
                    DELETE FROM feat_map WHERE fc_id = %s;
                    """,
                    (feature_collection_id,),
                )
                # delete all features that are not associated with any feature collection
                cur.execute(
                    """
                    DELETE FROM features WHERE id NOT IN (SELECT geom_id FROM feat_map);
                    """
                )

            if update_features or replace_features or not update_meta:
                for feature in feature_collection.features:
                    _insert_feature(cur, feature_collection_id, feature, check_existing=update_features)


def _get_feature_collection_id(cur: Cursor, name: str) -> int:
    cur.execute(
        """
        SELECT id FROM feature_collections WHERE name = %s;
        """,
        (name,),
    )
    result = cur.fetchone()
    if result is None:
        return None
    else:
        return result["id"]

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
            temporal_name = %(temporal_name)s,
            temporal_type = %(temporal_type)s,
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
            temporal_name,
            temporal_type,
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
            %(temporal_name)s,
            %(temporal_type)s,
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


def _insert_feature(cur: Cursor, feature_collection_id: int, feature: Feature, check_existing: bool = False) -> None:
    wkt = feature.geometry

    if check_existing:
        # check if geom is already in features table, returning any matching ids
        query = """
            SELECT
                f.id as geom_id,
                fm.id as fm_id,
                fm.fc_id as fc_id
            FROM (
                SELECT * FROM features
            ) AS f
            INNER JOIN (
                SELECT * FROM feat_map
            ) AS fm
            ON f.id = fm.geom_id
            WHERE fc_id = %s AND ST_Equals(ST_GeomFromText(%s), shape)
            ;
        """
        cur.execute(query, (feature_collection_id, wkt,), )
        result = cur.fetchone()["geom_id"]

        # query = """
        #     SELECT id FROM features WHERE ST_Equals(ST_GeomFromText(%s), shape)
        # """
        # cur.execute(query, (wkt,), )
        # result = cur.fetchone()

    else:

        cur.execute(
            """
            INSERT INTO features (shape) VALUES (ST_GeomFromText(%s)) RETURNING id;
            """,
            (wkt,),
        )
        result = cur.fetchone()["id"]


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
