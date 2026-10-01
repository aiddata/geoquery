import django.contrib.postgres.indexes
from django.contrib.postgres.operations import (
    AddIndexConcurrently,
    TrigramExtension,
    UnaccentExtension,
)
from django.db import migrations

import features.models

# unaccent() is STABLE because its dictionary can change, so Postgres refuses
# to index it. Naming the dictionary explicitly and schema-qualifying both
# calls makes the result depend only on the input, which is what IMMUTABLE
# promises -- and lets the planner inline it in features.models.NormalizedName.
CREATE_FUNCTION_SQL = """
CREATE FUNCTION geoquery_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;
"""

DROP_FUNCTION_SQL = "DROP FUNCTION IF EXISTS geoquery_unaccent(text);"


class Migration(migrations.Migration):
    # Required by AddIndexConcurrently. On production the build takes seconds
    # (26 MB over ~950k names, measured against a copy of the production
    # names) and holds no write lock.
    atomic = False

    dependencies = [
        ('features', '0009_feature_representative_point'),
    ]

    operations = [
        # Both are trusted extensions (PG13+), so the database owner can
        # create them without superuser.
        TrigramExtension(),
        UnaccentExtension(),
        migrations.RunSQL(sql=CREATE_FUNCTION_SQL, reverse_sql=DROP_FUNCTION_SQL),
        AddIndexConcurrently(
            model_name='featmap',
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.indexes.OpClass(
                    features.models.NormalizedName('name'), name='gin_trgm_ops'
                ),
                name='idx_feat_map_name_trgm',
            ),
        ),
    ]
