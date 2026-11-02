"""Utilities for maintaining the pre-simplified geometry tables used by the
vector tile endpoint.

These began life as materialized views (migration 0002) and became plain
tables in migration 0007 so they can be maintained incrementally: the
simplification window is PARTITION BY fc_id, so one collection's rows can be
recomputed without touching -- or locking -- any other collection's. A
DELETE+INSERT here takes only row locks, unlike REFRESH MATERIALIZED VIEW,
whose ACCESS EXCLUSIVE lock blocked every reader (and every concurrent
refresh) for the full multi-hour recompute of all collections at once.

features_points and features_point_cells ride along: one point per feature,
and those points pre-summed on a fixed grid, which vector tiles count and
cluster where a collection is too dense to draw as polygons (see
features.views). They are replaced in the same transaction as the simplified
tiers, so a tile never sees points and shapes from different versions.
"""

from django.db import connection, transaction
from loguru import logger

SIMPLIFIED_GEOMETRY_TABLES = [
    ("features_simplified_z0_5", 0.075),
    ("features_simplified_z6_9", 0.0025),
    ("features_simplified_z10_12", 0.0003),
]

# With WHERE fc_id = %s the window collapses to a single partition, so the
# rows produced are identical to what the old whole-table matview refresh
# computed for that collection. Ignore invalid geoms due to simplfication.
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


POINTS_TABLE = "features_points"

# The centroid, in the tile projection. ST_Centroid rather than
# ST_PointOnSurface: it never raises on an invalid geometry, which would fail
# the whole collection's update, and a cluster's position is a mean of these
# points anyway.
_INSERT_POINTS_SQL = f"""
    INSERT INTO {POINTS_TABLE} (fm_id, geom_id, fc_id, pt)
    SELECT fm.id, fm.geom_id, fm.fc_id, ST_Transform(ST_Centroid(f.shape), 3857)
    FROM feat_map fm
    JOIN features f ON fm.geom_id = f.id
    WHERE fm.fc_id = %s AND NOT ST_IsEmpty(f.shape)
"""

POINT_CELLS_TABLE = "features_point_cells"

# Half the width of the EPSG:3857 world, which spans [-HALF, HALF] on both axes.
WEB_MERCATOR_HALF_WIDTH = 20037508.342789244

# features_point_cells holds each collection's points summed on a grid of
# 2**POINT_CELLS_LEVEL cells per world axis, numbered like tiles: column ci
# from the west, row cj from the north. A tile's cluster cells are unions of
# these whenever they are no finer -- up to z7 with features.views'
# CLUSTER_GRID of 8 -- and above that tiles cluster from the points directly.
POINT_CELLS_LEVEL = 10


def cell_index_sql(level, x="ST_X(pt)", y="ST_Y(pt)"):
    """SQL for the (ci, cj) of a point on a 2**level grid.

    Shared by features_point_cells and the tile queries so a point always
    lands in the same cell, and so in exactly one tile. Clamped, so a point on
    the world's east or south edge stays in the last cell rather than falling
    off the grid.
    """
    n = 2**level
    w = WEB_MERCATOR_HALF_WIDTH
    return (
        f"LEAST(GREATEST(floor(({x} + {w}) * {n} / {2 * w})::integer, 0), {n - 1})",
        f"LEAST(GREATEST(floor(({w} - {y}) * {n} / {2 * w})::integer, 0), {n - 1})",
    )


_CI, _CJ = cell_index_sql(POINT_CELLS_LEVEL)
_INSERT_POINT_CELLS_SQL = f"""
    INSERT INTO {POINT_CELLS_TABLE} (fc_id, ci, cj, n, sx, sy)
    SELECT fc_id, ci, cj, count(*), sum(x), sum(y) FROM (
        SELECT fc_id, ST_X(pt) AS x, ST_Y(pt) AS y, {_CI} AS ci, {_CJ} AS cj
        FROM {POINTS_TABLE}
        WHERE fc_id = %s
    ) p
    GROUP BY fc_id, ci, cj
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
            cursor.execute(f"DELETE FROM {POINTS_TABLE} WHERE fc_id = %s", [fc_id])
            cursor.execute(_INSERT_POINTS_SQL, [fc_id])
            cursor.execute(f"DELETE FROM {POINT_CELLS_TABLE} WHERE fc_id = %s", [fc_id])
            cursor.execute(_INSERT_POINT_CELLS_SQL, [fc_id])
    logger.info(f"  Done: fc_id={fc_id}")


def remove_simplified_geometries(fc_id):
    """Delete one collection's rows from all simplified-geometry tables."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            for table in _tables():
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
            for table in _tables():
                cursor.execute(
                    f"DELETE FROM {table} "
                    "WHERE fc_id NOT IN (SELECT DISTINCT fc_id FROM feat_map)"
                )
    logger.info("Rebuild complete")


def _tables():
    """Every table maintained per collection here."""
    return [table for table, _ in SIMPLIFIED_GEOMETRY_TABLES] + [
        POINTS_TABLE,
        POINT_CELLS_TABLE,
    ]
