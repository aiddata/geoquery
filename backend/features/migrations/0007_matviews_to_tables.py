from django.db import migrations

# Convert the three simplified-geometry matviews into plain tables so they can
# be maintained incrementally per collection (see features.matviews). The
# current matview contents are carried over as-is: simplification is windowed
# PARTITION BY fc_id, so the carried-over rows are byte-identical to what a
# per-collection recompute would produce. If a matview is suspected stale at
# migration time, run `manage.py rebuild_simplified_geometries` afterwards -- it no longer
# blocks readers, so it can run any time.
#
# The copy runs before the DROP so the ACCESS EXCLUSIVE lock on the matview is
# only held from that statement to commit, not for the duration of the copy.

_CONVERT = """
    CREATE TABLE {view}_tbl AS TABLE {view};
    DROP MATERIALIZED VIEW {view} CASCADE;
    ALTER TABLE {view}_tbl RENAME TO {view};
    ALTER TABLE {view} ADD PRIMARY KEY (fm_id);
    CREATE INDEX {view}_fc_id_idx   ON {view} (fc_id);
    CREATE INDEX {view}_geom_id_idx ON {view} (geom_id);
    CREATE INDEX {view}_shape_idx   ON {view} USING GIST (shape);
"""

# Reverse: restore the 0004-era matview definition.
_RESTORE = """
    DROP TABLE IF EXISTS {view};
    CREATE MATERIALIZED VIEW {view} AS
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
    JOIN features f ON fm.geom_id = f.id;

    CREATE INDEX {view}_fc_id_idx   ON {view} (fc_id);
    CREATE INDEX {view}_geom_id_idx ON {view} (geom_id);
    CREATE INDEX {view}_shape_idx   ON {view} USING GIST (shape);
"""

MATVIEWS = [
    ("features_simplified_z0_5", 0.044),
    ("features_simplified_z6_9", 0.003),
    ("features_simplified_z10_12", 0.0003),
]


class Migration(migrations.Migration):
    dependencies = [
        ("features", "0006_featurecollection_short_name"),
    ]

    operations = [
        *(
            migrations.RunSQL(
                sql=_CONVERT.format(view=view),
                reverse_sql=_RESTORE.format(view=view, tolerance=tol),
            )
            for view, tol in MATVIEWS
        ),
    ]
