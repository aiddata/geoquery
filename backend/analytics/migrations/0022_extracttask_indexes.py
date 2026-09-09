from django.db import migrations


class Migration(migrations.Migration):
    """
    Adds the composite uniqueness/lookup index that replaces the old
    extract_tasks_resource_fm_po_kwargs_hash_idx (1.8GB on the pre-redesign
    table, zero reads across the whole incident -- nothing ever queried its
    exact hash expression). This one is ordered for the ad-hoc single-task
    lookup path (views.py/ingest.py's ExtractTask.objects.get/create with
    fm=, po=, resource_ids=), which is the only remaining source of
    potential duplicate-task races now that the bulk build path dedupes via
    extract_task_build_progress claiming (migration 0020) rather than a live
    anti-join against extract_tasks.

    extract_tasks_pending_idx (status=0 partial, backing dispatch/KEDA) is
    recreated here too -- it existed on the pre-redesign table (migration
    0014) but migration 0021's DROP TABLE + CREATE TABLE ... PARTITION BY
    rewrite dropped it along with everything else built on the old table.

    Note: extract_tasks is LIST-partitioned on dataset_id (migration 0021),
    and PostgreSQL requires every unique index on a partitioned table to
    include all partition key columns, so dataset_id is included as the
    leading column of both unique indexes below. This doesn't weaken the
    intended uniqueness: resource_ids values are always specific to a single
    dataset, so two rows that could ever collide on (fm_id, po_id,
    resource_ids[, kwargs hash]) necessarily already share the same
    dataset_id.
    """

    dependencies = [
        ("analytics", "0021_partition_extract_tasks_and_data"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX extract_tasks_fm_po_resources_null_kwargs_idx
                    ON extract_tasks (dataset_id, fm_id, po_id, resource_ids)
                    WHERE kwargs IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_fm_po_resources_null_kwargs_idx;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX extract_tasks_fm_po_resources_kwargs_hash_idx
                    ON extract_tasks (dataset_id, fm_id, po_id, resource_ids, MD5(kwargs::text))
                    WHERE kwargs IS NOT NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_fm_po_resources_kwargs_hash_idx;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE INDEX extract_tasks_pending_idx
                    ON extract_tasks (priority DESC, submit_time)
                    WHERE status = 0;
            """,
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_pending_idx;",
        ),
    ]
