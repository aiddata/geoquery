from django.db import migrations, models

# Above this, the conversion is a maintenance-window operation and is not
# something a deploy should start on its own: an in-place ALTER rewrites every
# partition in one transaction and holds ACCESS EXCLUSIVE throughout. Size,
# not reltuples, because reltuples is -1 on partitions that were never
# analyzed -- 34 of production's 57 at one point.
IN_PLACE_LIMIT_BYTES = 1 * 2**30

COLUMNS = (
    ("extract_tasks", "id"),
    ("extract_data", "extract_task_id"),
    ("request_map", "task_id"),
)


def _coltype(cursor, table, column):
    cursor.execute(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = %s::regclass AND attname = %s",
        [table, column],
    )
    return cursor.fetchone()[0]


def widen_task_ids(apps, schema_editor):
    """Make the three task-id columns bigint, or refuse if that needs a window.

    Already-bigint columns are left alone, so this is a no-op after
    convert_task_ids_to_bigint has done the production conversion. On a small
    database -- development, CI, a fresh install -- it converts in place,
    which is quick and keeps the foreign keys attached.
    """
    with schema_editor.connection.cursor() as cursor:
        pending = [(t, c) for t, c in COLUMNS if _coltype(cursor, t, c) != "bigint"]
        if not pending:
            return
        cursor.execute(
            "SELECT coalesce(sum(pg_total_relation_size(inhrelid)), 0) FROM pg_inherits "
            "WHERE inhparent IN ('extract_tasks'::regclass, 'extract_data'::regclass)"
        )
        size = cursor.fetchone()[0]
        if size > IN_PLACE_LIMIT_BYTES:
            raise RuntimeError(
                f"Task-id columns still integer: {', '.join(f'{t}.{c}' for t, c in pending)}. "
                f"extract_tasks + extract_data are {size / 2**30:,.0f} GB, too large to convert "
                "inside a migration. Run `manage.py convert_task_ids_to_bigint --execute` in a "
                "maintenance window first (database.md section 11), then deploy again."
            )
        for table, column in pending:
            cursor.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE bigint')
        # Widening an identity column does not raise its sequence's MAXVALUE;
        # without this, ids still stop at 2,147,483,647.
        cursor.execute(
            "ALTER TABLE extract_tasks ALTER COLUMN id SET MAXVALUE 9223372036854775807"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0030_extracttaskbuildrun_worker_tracking"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # Not reversed: a bigint column holds every int4 value, and
                # narrowing it back would fail once any id exceeds int4.
                migrations.RunPython(widen_task_ids, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="extracttask",
                    name="id",
                    field=models.BigAutoField(primary_key=True, serialize=False),
                ),
            ],
        ),
    ]
