import django.contrib.gis.db.models.fields
from django.contrib.postgres.indexes import GistIndex
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, transaction

# Rows per backfill transaction. Small enough that each UPDATE holds its row
# locks and pool connection for well under a second on production.
BATCH_SIZE = 10_000

# Keeps representative_point in step with shape on every write path, including
# QuerySet.update() and raw SQL, which bypass Feature.save(). Same rule as
# Feature.sync_representative_point(): fill it when null, and recompute it
# when shape changes unless the same write also supplies a new point.
# "UPDATE OF" limits firing to statements that mention one of the two columns,
# so unrelated updates never pay for the geometry comparison.
CREATE_TRIGGER_SQL = """
CREATE FUNCTION features_sync_representative_point() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.representative_point IS NULL
       OR (TG_OP = 'UPDATE'
           AND NEW.shape IS DISTINCT FROM OLD.shape
           AND NEW.representative_point IS NOT DISTINCT FROM OLD.representative_point)
    THEN
        NEW.representative_point := ST_Centroid(NEW.shape);
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER features_sync_representative_point
BEFORE INSERT OR UPDATE OF shape, representative_point ON features
FOR EACH ROW EXECUTE FUNCTION features_sync_representative_point();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS features_sync_representative_point ON features;
DROP FUNCTION IF EXISTS features_sync_representative_point();
"""


def backfill_representative_point(apps, schema_editor):
    """Set representative_point = ST_Centroid(shape) on existing rows, in batches.

    Done in id-range chunks, each in its own transaction, rather than as one
    UPDATE: with over a million features a single statement would hold the
    table's ACCESS EXCLUSIVE lock (taken by the AddField above) for the whole
    backfill and write all its WAL in one burst. The IS NULL predicate makes
    this idempotent, so a failed run can simply be re-applied.
    """
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT min(id), max(id) FROM features")
        lowest, highest = cursor.fetchone()
    if lowest is None:
        return

    for start in range(lowest, highest + 1, BATCH_SIZE):
        with transaction.atomic(using=connection.alias):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE features
                    SET representative_point = ST_Centroid(shape)
                    WHERE id >= %s AND id < %s AND representative_point IS NULL
                    """,
                    [start, start + BATCH_SIZE],
                )


class Migration(migrations.Migration):
    # Non-atomic so the AddField's table lock is released before the backfill
    # starts and each backfill batch commits on its own.
    atomic = False

    dependencies = [
        ('features', '0008_featurecollection_license_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='feature',
            name='representative_point',
            field=django.contrib.gis.db.models.fields.PointField(
                blank=True, null=True, spatial_index=False, srid=4326
            ),
        ),
        migrations.RunSQL(sql=CREATE_TRIGGER_SQL, reverse_sql=DROP_TRIGGER_SQL),
        migrations.RunPython(
            backfill_representative_point,
            reverse_code=migrations.RunPython.noop,
        ),
        # Built last and concurrently: one bulk build over populated rows with
        # no write lock, instead of an index the backfill has to maintain row
        # by row. Requires atomic = False above.
        AddIndexConcurrently(
            model_name='feature',
            index=GistIndex(fields=['representative_point'], name='idx_features_repr_point'),
        ),
    ]
