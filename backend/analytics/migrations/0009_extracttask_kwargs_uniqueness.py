from django.db import migrations


class Migration(migrations.Migration):
    """
    Replace the (resource, fm, po) unique constraint on extract_tasks with a
    functional unique index on (resource_id, fm_id, po_id, COALESCE(kwargs::text, '')).

    This allows multiple rows for the same (resource, fm, po) triplet when they
    carry different kwargs (e.g. different filter selections for filter_and_agg
    datasets), while preserving the existing one-row-per-triplet behaviour for
    tasks where kwargs IS NULL (zonal_stats and similar).
    """

    dependencies = [
        ("analytics", "0008_requesttoken_hash_existing"),
    ]

    operations = [
        # Drop the Django-managed unique constraint
        migrations.RunSQL(
            sql="ALTER TABLE extract_tasks DROP CONSTRAINT IF EXISTS extract_tasks_resource_fm_po_pk;",
            reverse_sql=(
                "ALTER TABLE extract_tasks ADD CONSTRAINT extract_tasks_resource_fm_po_pk "
                "UNIQUE (resource_id, fm_id, po_id);"
            ),
        ),
        # Add functional unique index covering kwargs
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS extract_tasks_resource_fm_po_kwargs_idx "
                "ON extract_tasks (resource_id, fm_id, po_id, COALESCE(kwargs::text, ''));"
            ),
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_resource_fm_po_kwargs_idx;",
        ),
    ]
