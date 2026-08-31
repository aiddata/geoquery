from django.db import migrations


class Migration(migrations.Migration):
    """
    Two index-size fixes on extract_tasks, found while investigating an
    incident where its indexes had bloated to ~400GB:

    1. Drop extract_tasks_id_unique. It was a UniqueConstraint on `id`, which
       is already the AutoField primary key -- a pure duplicate of
       extract_tasks_pkey costing a full extra btree on every row for no
       behavioural difference.

    2. Replace the 4-column composite unique index (resource_id, fm_id,
       po_id, MD5(kwargs) as text) with a single MD5 hash of all four
       values, stored as bytea. This is ~16 bytes/row versus ~45+ bytes/row
       for the four separate columns, while enforcing the identical
       uniqueness constraint. Nothing in the codebase issues ON CONFLICT
       against the old column list or otherwise depends on its shape --
       uniqueness is enforced purely at the DB level as a backstop behind
       build_extract_tasks' own NOT EXISTS check. resource_id/fm_id/po_id
       already have dedicated single-column indexes for lookups, so this
       index's only job is uniqueness enforcement.
    """

    dependencies = [
        ("analytics", "0012_merge_20260729_1730"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="extracttask",
            name="extract_tasks_id_unique",
        ),
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS extract_tasks_resource_fm_po_kwargs_idx;",
            reverse_sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS extract_tasks_resource_fm_po_kwargs_idx "
                "ON extract_tasks (resource_id, fm_id, po_id, MD5(COALESCE(kwargs::text, '')));"
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS extract_tasks_resource_fm_po_kwargs_hash_idx "
                "ON extract_tasks (("
                "  DECODE(MD5("
                "    resource_id::text || ':' || fm_id::text || ':' || po_id::text || ':' || COALESCE(kwargs::text, '')"
                "  ), 'hex')"
                "));"
            ),
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_resource_fm_po_kwargs_hash_idx;",
        ),
    ]
