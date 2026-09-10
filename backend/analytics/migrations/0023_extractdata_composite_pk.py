from django.db import migrations, models


# extract_data currently has ~1.27M rows in production and growing --
# unlike migration 0017's wipe-first approach, this ALTERs a live,
# non-empty table. Both operations below are cheap at this row count
# (NOT NULL validation and PK constraint validation are both single
# sequential scans, no full rewrite), but on a much larger table in the
# future this pattern would need CONCURRENTLY-style staging (add the
# constraint NOT VALID, then VALIDATE CONSTRAINT separately) rather than
# a straight ADD CONSTRAINT -- not needed yet at current volume.
#
# extract_data_pkey is currently PRIMARY KEY (dataset_id, id) (see
# migration 0021 -- dataset_id leads because Postgres requires the
# partition key in any PK/unique constraint on a LIST-partitioned table).
# Both the DROP CONSTRAINT/ADD CONSTRAINT PRIMARY KEY and the DROP COLUMN
# below act on the partitioned parent and propagate automatically to every
# existing partition (extract_data_default and each extract_data_ds_<id>),
# the same way migration 0021's ADD CONSTRAINT did for the FK it added.
_FORWARD_SQL = """
    ALTER TABLE extract_data ALTER COLUMN name SET NOT NULL;
    ALTER TABLE extract_data DROP CONSTRAINT extract_data_pkey;
    ALTER TABLE extract_data ADD PRIMARY KEY (dataset_id, extract_task_id, name);
    ALTER TABLE extract_data DROP COLUMN id;
"""

# Re-adding the surrogate id column on reverse would need a fresh identity
# sequence and wouldn't reconstruct the original values -- reversing this
# migration is only meaningful before any data has been written under the
# new schema. Matches the same one-way-in-practice posture as migration
# 0017's wipe (documented there as acceptable given the data is
# regenerable); here reversal is simply unsupported rather than lossy.
_REVERSE_SQL = migrations.RunSQL.noop


class Migration(migrations.Migration):
    """
    Replaces ExtractData's surrogate BigAutoField id with the natural
    (dataset_id, extract_task_id, name) composite key. (extract_task, name)
    was always the real uniqueness constraint (0 duplicates confirmed in
    production data); dataset_id leads because Postgres requires the
    partition key in any PK/unique constraint on a partitioned table
    (extract_data is LIST-partitioned on dataset_id, migration 0021).

    Dropping id also drops its own now-redundant PK index -- this is the
    entire point of the migration, not a side effect to work around.
    """

    dependencies = [
        ("analytics", "0022_extracttask_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
            state_operations=[
                migrations.AlterField(
                    model_name="extractdata",
                    name="name",
                    field=models.CharField(max_length=100),
                ),
                migrations.RemoveField(
                    model_name="extractdata",
                    name="id",
                ),
                migrations.AddField(
                    model_name="extractdata",
                    name="pk",
                    field=models.CompositePrimaryKey("dataset_id", "extract_task", "name"),
                ),
            ],
        ),
    ]
