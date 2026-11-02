from django.db import migrations, transaction

# One point per feat_map row, in EPSG:3857, for vector tiles to count and
# cluster where a collection is too dense to draw as polygons; and the same
# points summed per collection on a fixed 1024x1024 world grid, so low-zoom
# tiles cluster from a few thousand cells rather than every point (606k for
# India ADM5 in one z2 tile). Maintained per collection with the
# simplified-geometry tables (features.matviews).
#
# GIST (fc_id, pt) for the same reason as 0011: tiles filter on the selected
# collections and the tile envelope together, and that index answers both.
# btree_gist (for fc_id) was installed by 0011. It also serves the per-
# collection DELETE in features.matviews, so there is no separate fc_id index.

CREATE_TABLE_SQL = """
CREATE TABLE features_points (
    fm_id integer PRIMARY KEY,
    geom_id integer NOT NULL,
    fc_id integer NOT NULL,
    pt geometry(Point, 3857) NOT NULL
);
"""

# The primary key serves the tile query: fc_id equality, then a ci range.
CREATE_CELLS_TABLE_SQL = """
CREATE TABLE features_point_cells (
    fc_id integer NOT NULL,
    ci integer NOT NULL,
    cj integer NOT NULL,
    n integer NOT NULL,
    sx double precision NOT NULL,
    sy double precision NOT NULL,
    PRIMARY KEY (fc_id, ci, cj)
);
"""

CREATE_INDEX_SQL = (
    "CREATE INDEX features_points_fc_id_pt_idx ON features_points USING GIST (fc_id, pt)"
)

# A copy of features.matviews._INSERT_POINTS_SQL as of this migration, so a
# later change there cannot alter what this migration does.
_INSERT_SQL = """
    INSERT INTO features_points (fm_id, geom_id, fc_id, pt)
    SELECT fm.id, fm.geom_id, fm.fc_id, ST_Transform(ST_Centroid(f.shape), 3857)
    FROM feat_map fm
    JOIN features f ON fm.geom_id = f.id
    WHERE fm.fc_id = %s AND NOT ST_IsEmpty(f.shape)
"""

# Likewise features.matviews._INSERT_POINT_CELLS_SQL, at level 10.
_HALF = 20037508.342789244
_INSERT_CELLS_SQL = f"""
    INSERT INTO features_point_cells (fc_id, ci, cj, n, sx, sy)
    SELECT fc_id, ci, cj, count(*), sum(x), sum(y) FROM (
        SELECT fc_id, ST_X(pt) AS x, ST_Y(pt) AS y,
            LEAST(GREATEST(floor((ST_X(pt) + {_HALF}) * 1024 / {2 * _HALF})::integer, 0), 1023) AS ci,
            LEAST(GREATEST(floor(({_HALF} - ST_Y(pt)) * 1024 / {2 * _HALF})::integer, 0), 1023) AS cj
        FROM features_points
        WHERE fc_id = %s
    ) p
    GROUP BY fc_id, ci, cj
"""


def backfill(apps, schema_editor):
    """Fill points for every collection the tiles serve, one transaction each.

    Those are the collections with simplified rows; user uploads have none
    (their tiles are simplified per request) and get no points either.
    Per-collection transactions keep each one short, like
    rebuild_simplified_geometries.
    """
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT DISTINCT fc_id FROM features_simplified_z0_5 ORDER BY fc_id")
        fc_ids = [row[0] for row in cursor.fetchall()]

    for fc_id in fc_ids:
        with transaction.atomic(using=connection.alias):
            with connection.cursor() as cursor:
                cursor.execute(_INSERT_SQL, [fc_id])
                cursor.execute(_INSERT_CELLS_SQL, [fc_id])


class Migration(migrations.Migration):
    # The backfill commits per collection. The table is new and nothing reads
    # it until this release, so the index is built plainly, after the backfill,
    # rather than maintained row by row during it.
    atomic = False

    dependencies = [
        ('features', '0012_remove_feature_representative_point'),
    ]

    operations = [
        migrations.RunSQL(CREATE_TABLE_SQL, reverse_sql="DROP TABLE features_points"),
        migrations.RunSQL(
            CREATE_CELLS_TABLE_SQL, reverse_sql="DROP TABLE features_point_cells"
        ),
        migrations.RunPython(backfill, reverse_code=migrations.RunPython.noop),
        migrations.RunSQL(
            CREATE_INDEX_SQL,
            reverse_sql="DROP INDEX IF EXISTS features_points_fc_id_pt_idx",
        ),
        migrations.RunSQL(
            "ANALYZE features_points; ANALYZE features_point_cells",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
