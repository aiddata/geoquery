from django.db import migrations

# Recreate matviews with geom_id added so MVT tiles can expose Feature.id
# for client-side feature selection.
_CREATE = """
    DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE;
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

    CREATE INDEX {view}_fc_id_idx  ON {view} (fc_id);
    CREATE INDEX {view}_geom_id_idx ON {view} (geom_id);
    CREATE INDEX {view}_shape_idx  ON {view} USING GIST (shape);
"""

# Reverse: restore 0003 state (no geom_id column)
_RESTORE = """
    DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE;
    CREATE MATERIALIZED VIEW {view} AS
    SELECT
        fm.id AS fm_id,
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

    CREATE INDEX {view}_fc_id_idx ON {view} (fc_id);
    CREATE INDEX {view}_shape_idx ON {view} USING GIST (shape);
"""

MATVIEWS = [
    ("features_simplified_z0_5", 0.044),
    ("features_simplified_z6_9", 0.003),
    ("features_simplified_z10_12", 0.0003),
]


class Migration(migrations.Migration):
    dependencies = [
        ("features", "0003_composite_matview_indexes"),
    ]

    operations = [
        *(
            migrations.RunSQL(
                sql=_CREATE.format(view=view, tolerance=tol),
                reverse_sql=_RESTORE.format(view=view, tolerance=tol),
            )
            for view, tol in MATVIEWS
        ),
    ]
