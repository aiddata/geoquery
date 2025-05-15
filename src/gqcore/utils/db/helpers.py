from typing import Dict

import psycopg
import shapely
from loguru import logger
from psycopg import Cursor
from psycopg.types.json import Jsonb

from gqcore.utils.db.conn import get_conn
from gqcore.utils.models import DatasetResource, ExtractTask, ProcessingOption


def get_dataset_by_name(name: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            dataset_info = _get_dataset_by_name(cur, name)
            return dataset_info


@logger.catch(reraise=True)
def _get_dataset_by_name(cur: Cursor, name: str) -> dict:
    query = "SELECT * from datasets WHERE name = %s"
    cur.execute(query, (name,))
    dataset_info = cur.fetchone()
    return dataset_info


def get_dataset_resource_path_by_id(id: int) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            path = _get_dataset_resource_path_by_id(cur, id)
    return path


@logger.catch(reraise=True)
def _get_dataset_resource_path_by_id(cur: Cursor, id: int) -> str:
    query = """SELECT path FROM dataset_resources WHERE id = %s""", (id,)
    path = cur.execute(query).fetchone()
    return path


def get_feat_geom_by_id(id: int) -> shapely.geometry.base.BaseGeometry:
    with get_conn() as conn:
        with conn.cursor() as cur:
            feat = _get_feat_geom_by_id(cur, id)
    return feat


@logger.catch(reraise=True)
def _get_feat_geom_by_id(cur: Cursor, id: int) -> shapely.geometry.base.BaseGeometry:
    query = """SELECT shape FROM features WHERE id = %s"""
    geom = cur.execute(query, (id,)).fetchone()
    feat = shapely.wkb.loads(geom["shape"], hex=True)
    return feat


def get_dataset_extent_by_id(id: int) -> shapely.geometry.base.BaseGeometry:
    with get_conn() as conn:
        with conn.cursor() as cur:
            feat = _get_dataset_extent_by_id(cur, id)
    return feat


@logger.catch(reraise=True)
def _get_dataset_extent_by_id(
    cur: Cursor, id: int
) -> shapely.geometry.base.BaseGeometry:
    query = """SELECT spatial_extent FROM datasets WHERE id = %s"""
    extent = cur.execute(query, (id,)).fetchone()
    feat = shapely.wkb.loads(extent["spatial_extent"], hex=True)
    return feat


def get_coverage_records(status=None) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            coverage = _get_coverage_records(cur, status)
            return coverage


@logger.catch(reraise=True)
def _get_coverage_records(cur: Cursor, status=None) -> list:
    coverage_query = "SELECT * FROM coverage"
    if status is not None:
        coverage_query += " WHERE status = %s" % status
    cur.execute(coverage_query)
    coverage = cur.fetchall()
    return coverage


def update_coverage_status(geom_id: int, dataset_id: int, status: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _update_coverage_status(cur, geom_id, dataset_id, status)


@logger.catch(reraise=True)
def _update_coverage_status(
    cur: Cursor, geom_id: int, dataset_id: int, status: int
) -> None:
    cur.execute(
        """
        UPDATE coverage
        SET status = %s
        WHERE geom_id = %s AND dataset_id = %s;
        """,
        (status, geom_id, dataset_id),
    )


def get_feature_ids() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            feature_ids = _get_feature_ids(cur)
            return feature_ids


@logger.catch(reraise=True)
def _get_feature_ids(cur: Cursor) -> list:
    feature_query = "SELECT id FROM features"
    cur.execute(feature_query)
    feature_ids = cur.fetchall()
    return feature_ids


@logger.catch(reraise=True)
def get_dataset_ids_without_coverage_dependencies() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            dataset_query = "SELECT id FROM datasets WHERE coverage_dependency IS null"
            cur.execute(dataset_query)
            dataset_ids = cur.fetchall()
            return dataset_ids


def find_missing_coverage_id_pairs() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            results = _find_missing_coverage_id_pairs(cur)
            return results


@logger.catch(reraise=True)
def _find_missing_coverage_id_pairs(cur: Cursor) -> list:
    # get all ids from datasets table and ids from features table where the pair does not yet exist in the coverage table
    coverage_query = """
        SELECT s.geom_id, s.dataset_id FROM (
            SELECT
                f.geom_id,
                d.dataset_id
            FROM (
                SELECT id AS geom_id FROM features
            ) AS f
            CROSS JOIN (
                SELECT id AS dataset_id FROM datasets WHERE coverage_dependency IS null
            ) AS d
        ) as s
        LEFT OUTER JOIN coverage ON s.geom_id = coverage.geom_id AND s.dataset_id = coverage.dataset_id
        WHERE coverage.geom_id IS NULL
        ;
    """

    cur.execute(coverage_query)
    results = cur.fetchall()
    return results


def get_dataset_ids() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            dataset_ids = _get_dataset_ids(cur)
            return dataset_ids


@logger.catch(reraise=True)
def _get_dataset_ids(cur: Cursor) -> list:
    dataset_query = "SELECT id FROM datasets"
    cur.execute(dataset_query)
    dataset_ids = cur.fetchall()
    return dataset_ids


def insert_coverage_records(coverage_list: list) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _insert_coverage_records(cur, coverage_list)


@logger.catch(reraise=True)
def _insert_coverage_records(cur: Cursor, coverage_list: list) -> int:
    for c in coverage_list:
        cur.execute(
            """
            INSERT INTO coverage (geom_id, dataset_id, status)
            VALUES (%s, %s, %s)
            ON CONFLICT (geom_id, dataset_id)
            DO NOTHING
            ;
            """,
            (c.geom_id, c.dataset_id, c.status),
        )


def get_dataset_by_id(dataset_id: int) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            dataset_info = _get_dataset_by_id(cur, dataset_id)
            return dataset_info


@logger.catch(reraise=True)
def _get_dataset_by_id(cur: Cursor, dataset_id: int) -> list:
    resource_query = "SELECT * from dataset_resources WHERE dataset_id = %s"
    cur.execute(resource_query, (dataset_id,))
    dataset_info = cur.fetchall()
    return dataset_info


def get_processing_options_by_dataset(dataset_id: int) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            po_info = _get_processing_options_by_dataset(cur, dataset_id)
            return po_info


@logger.catch(reraise=True)
def _get_processing_options_by_dataset(cur: Cursor, dataset_id: int) -> list:
    resource_query = (
        "SELECT * from processing_options WHERE dataset_id = %s AND active = True"
    )
    cur.execute(resource_query, (dataset_id,))
    po_info = cur.fetchall()
    return po_info


def insert_extract_task(task: ExtractTask, overwrite: bool = False) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _insert_extract_task(cur, task, overwrite)


@logger.catch(reraise=True)
def _insert_extract_task(
    cur: Cursor, task: ExtractTask, overwrite: bool = False
) -> None:
    if overwrite:
        conflict_str = "DO UPDATE SET status = excluded.status, priority = excluded.priority, submit_time = excluded.submit_time, kwargs = excluded.kwargs"
    else:
        conflict_str = "DO NOTHING"

    insert = """
        INSERT INTO extract_tasks (resource_id, fm_id, po_id, status, priority, submit_time, kwargs)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (resource_id, fm_id, po_id)
        """
    insert += conflict_str
    cur.execute(
        insert,
        (
            task.resource_id,
            task.fm_id,
            task.po_id,
            task.status,
            task.priority,
            task.submit_time,
            task.kwargs,
        ),
    )


def insert_dataset_resource(dataset_id: int, resource: DatasetResource):
    with get_conn() as conn:
        with conn.cursor() as cur:
            _insert_dataset_resource(cur, dataset_id, resource)


@logger.catch(reraise=True)
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


def insert_processing_option(
    dataset_id: int, processing_option: ProcessingOption
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _insert_processing_option(cur, dataset_id, processing_option)


@logger.catch(reraise=True)
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
            result_type,
            kwargs
        ) VALUES (
            %(dataset_id)s,
            %(active)s,
            %(public)s,
            %(short_name)s,
            %(function)s,
            %(result_type)s,
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


def insert_mappings(dataset_id: int, mappings: Dict[str, int]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _insert_mappings(cur, dataset_id, mappings)


@logger.catch(reraise=True)
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


def deactivate_processing_options(dataset_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _deactivate_processing_options(cur, dataset_id)


@logger.catch(reraise=True)
def _deactivate_processing_options(cur: Cursor, dataset_id: int) -> None:
    cur.execute(
        "UPDATE processing_options SET active = False WHERE dataset_id = %s ;",
        (dataset_id,),
    )


def update_dataset_from_resources(dataset_id: int, dset_params: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _update_dataset_from_resources(cur, dataset_id, dset_params)


@logger.catch(reraise=True)
def _update_dataset_from_resources(cur, dataset_id: int, dset_params: dict) -> None:
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


def insert_dataset(params: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            dataset_id = _insert_dataset(cur, params)
            return dataset_id


@logger.catch(reraise=True)
def _insert_dataset(cur: Cursor, params: dict) -> int:
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
    cur.execute(query, params)
    dataset_id = cur.fetchone()["id"]
    return dataset_id


def update_dataset(params: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            dataset_id = _update_dataset(cur, params)
            return dataset_id


@logger.catch(reraise=True)
def _update_dataset(cur: Cursor, params: dict) -> int:
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

    cur.execute(query, params)
    result = cur.fetchone()
    if result:
        dataset_id = result["id"]
    else:
        dataset_id = None
    return dataset_id
