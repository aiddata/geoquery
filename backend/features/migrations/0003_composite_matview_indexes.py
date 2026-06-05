from django.db import migrations

# Template for recreating a matview with geometry stored in EPSG:3857.
# This eliminates per-row ST_Transform during tile serving since
# ST_TileEnvelope already returns 3857.
_CREATE_MATVIEW_3857 = """
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

# Reverse: restore original 4326 matviews from migration 0002
_RESTORE_MATVIEW_4326 = """
    DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE;
    CREATE MATERIALIZED VIEW {view} AS
    SELECT
        fm.id AS fm_id,
        fm.fc_id,
        fm.name,
        fm.attr,
        ST_SetSRID(
            ST_CoverageSimplify(f.shape, {tolerance})
                OVER (PARTITION BY fm.fc_id),
            4326
        ) AS shape
    FROM feat_map fm
    JOIN features f ON fm.geom_id = f.id;

    CREATE INDEX idx_{view}_fc_id ON {view} (fc_id);
    CREATE INDEX idx_{view}_shape ON {view} USING GIST (shape);
"""

MATVIEWS = [
    ("features_simplified_z0_5", 0.044),
    ("features_simplified_z6_9", 0.003),
    ("features_simplified_z10_12", 0.0003),
]


class Migration(migrations.Migration):
    dependencies = [
        ("features", "0002_simplified_geometry_matviews"),
    ]

    operations = [
        # Recreate each matview with geometry in EPSG:3857
        *(
            migrations.RunSQL(
                sql=_CREATE_MATVIEW_3857.format(view=view, tolerance=tol),
                reverse_sql=_RESTORE_MATVIEW_4326.format(view=view, tolerance=tol),
            )
            for view, tol in MATVIEWS
        ),
        # B-tree on feat_map(fc_id, geom_id) for z13+ raw table joins
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_feat_map_fc_geom ON feat_map (fc_id, geom_id);",
            reverse_sql="DROP INDEX IF EXISTS idx_feat_map_fc_geom;",
        ),
        # GiST on features(shape) for z13+ spatial filter
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_features_shape ON features USING GIST (shape);",
            reverse_sql="DROP INDEX IF EXISTS idx_features_shape;",
        ),
    ]
