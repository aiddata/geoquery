from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("features", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE MATERIALIZED VIEW features_simplified_z0_5 AS
                SELECT
                    fm.id AS fm_id,
                    fm.fc_id,
                    fm.name,
                    fm.attr,
                    ST_SetSRID(
                        ST_CoverageSimplify(f.shape, 0.044)
                            OVER (PARTITION BY fm.fc_id),
                        4326
                    ) AS shape
                FROM feat_map fm
                JOIN features f ON fm.geom_id = f.id;

                CREATE INDEX idx_features_simplified_z0_5_fc_id
                    ON features_simplified_z0_5 (fc_id);
                CREATE INDEX idx_features_simplified_z0_5_shape
                    ON features_simplified_z0_5 USING GIST (shape);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS features_simplified_z0_5;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE MATERIALIZED VIEW features_simplified_z6_9 AS
                SELECT
                    fm.id AS fm_id,
                    fm.fc_id,
                    fm.name,
                    fm.attr,
                    ST_SetSRID(
                        ST_CoverageSimplify(f.shape, 0.003)
                            OVER (PARTITION BY fm.fc_id),
                        4326
                    ) AS shape
                FROM feat_map fm
                JOIN features f ON fm.geom_id = f.id;

                CREATE INDEX idx_features_simplified_z6_9_fc_id
                    ON features_simplified_z6_9 (fc_id);
                CREATE INDEX idx_features_simplified_z6_9_shape
                    ON features_simplified_z6_9 USING GIST (shape);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS features_simplified_z6_9;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE MATERIALIZED VIEW features_simplified_z10_12 AS
                SELECT
                    fm.id AS fm_id,
                    fm.fc_id,
                    fm.name,
                    fm.attr,
                    ST_SetSRID(
                        ST_CoverageSimplify(f.shape, 0.0003)
                            OVER (PARTITION BY fm.fc_id),
                        4326
                    ) AS shape
                FROM feat_map fm
                JOIN features f ON fm.geom_id = f.id;

                CREATE INDEX idx_features_simplified_z10_12_fc_id
                    ON features_simplified_z10_12 (fc_id);
                CREATE INDEX idx_features_simplified_z10_12_shape
                    ON features_simplified_z10_12 USING GIST (shape);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS features_simplified_z10_12;",
        ),
    ]
