"""Utilities for maintaining the pre-simplified geometry tables used by the
vector tile endpoint.

These began life as materialized views (migration 0002) and became plain
tables in migration 0007 so they can be maintained incrementally: the
simplification window is PARTITION BY fc_id, so one collection's rows can be
recomputed without touching -- or locking -- any other collection's. A
DELETE+INSERT here takes only row locks, unlike REFRESH MATERIALIZED VIEW,
whose ACCESS EXCLUSIVE lock blocked every reader (and every concurrent
refresh) for the full multi-hour recompute of all collections at once.
"""

from django.db import connection, transaction
from loguru import logger

SIMPLIFIED_GEOMETRY_TABLES = [
    ("features_simplified_z0_5", 0.5),
    ("features_simplified_z6_9", 0.005),
    ("features_simplified_z10_12", 0.0003),
]

# With WHERE fc_id = %s the window collapses to a single partition, so the
# rows produced are identical to what the old whole-table matview refresh
# computed for that collection.
_INSERT_SQL = """
    INSERT INTO {table} (fm_id, geom_id, fc_id, name, attr, shape)
    SELECT fm_id, geom_id, fc_id, name, attr, shape FROM (
        SELECT
            fm.id AS fm_id,
            fm.geom_id,
            fm.fc_id,
            fm.name,
            fm.attr,
            ST_Transform(
                ST_SetSRID(
                    ST_CoverageSimplify(f.shape, {tolerance})
                        OVER (PARTITION BY fm.fc_id),
                    4326
                ),
                3857
            ) AS shape
        FROM feat_map fm
        JOIN features f ON fm.geom_id = f.id
        WHERE fm.fc_id = %s
    ) simplified
    WHERE NOT ST_IsEmpty(shape) AND ST_IsValid(shape)
"""


def update_simplified_geometries(fc_id):
    """Recompute one collection's rows in all simplified-geometry tables.

    All three tiers are replaced in a single transaction, so tile readers see
    either the old rows or the new rows for this collection, never a gap or a
    mixed zoom state.
    """
    logger.info(f"Updating simplified geometries for fc_id={fc_id}")
    with transaction.atomic():
        with connection.cursor() as cursor:
            for table, tolerance in SIMPLIFIED_GEOMETRY_TABLES:
                cursor.execute(f"DELETE FROM {table} WHERE fc_id = %s", [fc_id])
                cursor.execute(
                    _INSERT_SQL.format(table=table, tolerance=tolerance), [fc_id]
                )
    logger.info(f"  Done: fc_id={fc_id}")


def remove_simplified_geometries(fc_id):
    """Delete one collection's rows from all simplified-geometry tables."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            for table, _ in SIMPLIFIED_GEOMETRY_TABLES:
                cursor.execute(f"DELETE FROM {table} WHERE fc_id = %s", [fc_id])


def rebuild_simplified_geometries():
    """Rebuild every collection's simplified rows from the source features.

    One transaction per collection rather than one global transaction: a full
    rebuild can take a long time, and this keeps each unit of work small,
    resumable, and invisible to readers of the other collections.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT DISTINCT fc_id FROM feat_map ORDER BY fc_id")
        fc_ids = [row[0] for row in cursor.fetchall()]

    logger.info(f"Rebuilding simplified geometries for {len(fc_ids)} collections")
    for i, fc_id in enumerate(fc_ids, 1):
        update_simplified_geometries(fc_id)
        logger.info(f"  [{i}/{len(fc_ids)}] fc_id={fc_id}")

    # Collections deleted without going through the post_delete signal leave
    # simplified rows behind with no feat_map counterpart; sweep them here.
    with transaction.atomic():
        with connection.cursor() as cursor:
            for table, _ in SIMPLIFIED_GEOMETRY_TABLES:
                cursor.execute(
                    f"DELETE FROM {table} "
                    "WHERE fc_id NOT IN (SELECT DISTINCT fc_id FROM feat_map)"
                )
    logger.info("Rebuild complete")
