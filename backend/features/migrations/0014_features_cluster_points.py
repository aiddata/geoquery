from django.db import migrations

# Map clusters move off the fixed grid: each collection's points are clustered
# once for every zoom tiles cluster at (features.clusters), and tiles merge the
# selected collections' clusters (features.views). That replaces
# features_point_cells, the grid the tiles summed.
#
# id breaks ties between clusters of equal weight when tiles merge them, so it
# must be the same for every tile; a rebuild renumbers rows, which is fine.
#
# GIST (fc_id, z, pt): tiles read the selected collections' clusters at one
# zoom, around the tile. btree_gist (for fc_id, z) was installed by 0011. It
# also serves the per-collection DELETE in features.matviews.

CREATE_TABLE_SQL = """
CREATE TABLE features_cluster_points (
    id bigserial PRIMARY KEY,
    fc_id integer NOT NULL,
    z integer NOT NULL,
    n integer NOT NULL,
    pt geometry(Point, 3857) NOT NULL
);
"""

CREATE_INDEX_SQL = (
    "CREATE INDEX features_cluster_points_fc_id_z_pt_idx"
    " ON features_cluster_points USING GIST (fc_id, z, pt)"
)

RECREATE_CELLS_TABLE_SQL = """
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


def backfill(apps, schema_editor):
    """Cluster every collection that has points, one transaction each.

    Calls features.matviews directly rather than a frozen copy: clustering is
    numpy over features_points, which this migration's dependencies fix, and a
    copy would have to carry the whole algorithm. All of production takes
    seconds.
    """
    from features.matviews import rebuild_cluster_points

    rebuild_cluster_points()


class Migration(migrations.Migration):
    # The backfill commits per collection, like 0013's. The table is new and
    # nothing reads it until this release, so the index is built after it.
    atomic = False

    dependencies = [
        ("features", "0013_features_points"),
    ]

    operations = [
        migrations.RunSQL(CREATE_TABLE_SQL, reverse_sql="DROP TABLE features_cluster_points"),
        migrations.RunPython(backfill, reverse_code=migrations.RunPython.noop),
        migrations.RunSQL(
            CREATE_INDEX_SQL,
            reverse_sql="DROP INDEX IF EXISTS features_cluster_points_fc_id_z_pt_idx",
        ),
        migrations.RunSQL(
            "ANALYZE features_cluster_points", reverse_sql=migrations.RunSQL.noop
        ),
        # Reversing leaves the recreated table empty: run
        # `manage.py rebuild_simplified_geometries` on the older code to refill it.
        migrations.RunSQL(
            "DROP TABLE features_point_cells", reverse_sql=RECREATE_CELLS_TABLE_SQL
        ),
    ]
