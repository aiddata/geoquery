from django.db import migrations


class Migration(migrations.Migration):
    """
    Replace the functional unique index on extract_tasks kwargs text with an
    MD5-hashed version. The raw kwargs JSON can exceed PostgreSQL's 8191-byte
    B-tree index row limit (e.g. UCDP filter selections with thousands of
    conflict/dyad names). MD5 always produces a 32-char string well within
    the limit while still guaranteeing uniqueness per (resource, fm, po, kwargs)
    combination.
    """

    dependencies = [
        ("analytics", "0010_int_value_bigint"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS extract_tasks_resource_fm_po_kwargs_idx;",
            reverse_sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS extract_tasks_resource_fm_po_kwargs_idx "
                "ON extract_tasks (resource_id, fm_id, po_id, COALESCE(kwargs::text, ''));"
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS extract_tasks_resource_fm_po_kwargs_idx "
                "ON extract_tasks (resource_id, fm_id, po_id, MD5(COALESCE(kwargs::text, '')));"
            ),
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_resource_fm_po_kwargs_idx;",
        ),
    ]
