from django.db import migrations, models
from django.db.models import F, Func


# Adds the hashed column and rebuilds both resource_ids-keyed unique
# indexes to use it instead of the raw array. extract_tasks currently has
# tens of millions of rows and counting in production -- unlike migration
# 0022 (which built its indexes against an empty, just-wiped table), this
# runs against a live, growing, partitioned table. CREATE INDEX CONCURRENTLY
# is not used here for the same reason migration 0022's docstring gives:
# it's unsupported directly on a partitioned table (Postgres requires the
# per-partition CONCURRENTLY-then-ATTACH dance instead), which is a bigger
# undertaking than this migration -- the DROP+CREATE below will briefly
# hold an ACCESS EXCLUSIVE lock on this table (and each partition) while
# rebuilding, blocking reads/writes for that span. Time this against a
# prod-sized copy before deploying and prefer a lower-traffic window --
# don't assume "index rebuild" is automatically cheap at tens of millions
# of rows the way it was against migration 0022's empty table.
#
# The GENERATED column expression can't literally be
# `hashtext(resource_ids::text)`: Postgres declares the generic
# array-to-text cast (array_out) STABLE, not IMMUTABLE -- it's a
# type-generic function and Postgres can't assume every element type's
# output function is immutable, even though int4's always is -- and
# PostgreSQL rejects any non-IMMUTABLE expression in a GENERATED column
# ("generation expression is not immutable"), confirmed empirically against
# this table's actual Postgres 17 instance before writing this migration.
# extract_tasks_resource_ids_hash() below works around that: it's a tiny SQL
# function whose body is exactly `hashtext($1::text)` (byte-for-byte the
# same computation, just wrapped), declared IMMUTABLE. That's safe
# specifically because resource_ids is integer[] -- int4's text
# representation has no locale/session-dependent behavior, so the function
# genuinely always returns the same output for the same input, which is all
# IMMUTABLE actually promises. It would NOT be safe to slap IMMUTABLE on an
# array of a type whose output function truly varies (e.g. depends on
# search_path or collation).
_ADD_HASH_COLUMN_SQL = """
    CREATE FUNCTION extract_tasks_resource_ids_hash(ids integer[])
        RETURNS integer
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        STRICT
        AS $$ SELECT hashtext(ids::text) $$;

    ALTER TABLE extract_tasks
        ADD COLUMN resource_ids_hash INTEGER
        GENERATED ALWAYS AS (extract_tasks_resource_ids_hash(resource_ids)) STORED;
"""

_REBUILD_INDEXES_SQL = """
    DROP INDEX IF EXISTS extract_tasks_fm_po_resources_null_kwargs_idx;
    CREATE UNIQUE INDEX extract_tasks_fm_po_resources_null_kwargs_idx
        ON extract_tasks (dataset_id, fm_id, po_id, resource_ids_hash)
        WHERE kwargs IS NULL;

    DROP INDEX IF EXISTS extract_tasks_fm_po_resources_kwargs_hash_idx;
    CREATE UNIQUE INDEX extract_tasks_fm_po_resources_kwargs_hash_idx
        ON extract_tasks (dataset_id, fm_id, po_id, resource_ids_hash, MD5(kwargs::text))
        WHERE kwargs IS NOT NULL;
"""

# Rebuilds the two indexes back onto the raw resource_ids array, then drops
# the generated column. The wrapper function is dropped separately, by
# _ADD_HASH_COLUMN_SQL's own reverse below -- reverse_sql operations run in
# the opposite order from their forward counterparts, so by the time that
# runs, this has already dropped the column that depended on the function.
_REVERSE_SQL = """
    DROP INDEX IF EXISTS extract_tasks_fm_po_resources_null_kwargs_idx;
    CREATE UNIQUE INDEX extract_tasks_fm_po_resources_null_kwargs_idx
        ON extract_tasks (dataset_id, fm_id, po_id, resource_ids)
        WHERE kwargs IS NULL;

    DROP INDEX IF EXISTS extract_tasks_fm_po_resources_kwargs_hash_idx;
    CREATE UNIQUE INDEX extract_tasks_fm_po_resources_kwargs_hash_idx
        ON extract_tasks (dataset_id, fm_id, po_id, resource_ids, MD5(kwargs::text))
        WHERE kwargs IS NOT NULL;

    ALTER TABLE extract_tasks DROP COLUMN resource_ids_hash;
"""

_REVERSE_ADD_HASH_COLUMN_SQL = """
    DROP FUNCTION IF EXISTS extract_tasks_resource_ids_hash(integer[]);
"""


class Migration(migrations.Migration):
    """
    Adds extract_tasks.resource_ids_hash (a stored generated column,
    value-identical to hashtext(resource_ids::text) -- see
    extract_tasks_resource_ids_hash() below for why it isn't spelled that
    way directly) and rebuilds both resource_ids-keyed unique indexes to use
    it instead of the raw array. resource_ids can be up to 12 integers
    (grouped tasks) vs a fixed 4-byte hash, so this shrinks the largest
    index in the schema (extract_tasks_fm_po_resources_null_kwargs_idx was
    34% of the table's total footprint at ~62M rows).

    dataset_id/fm_id/po_id stay as plain columns leading both indexes --
    only the expensive variable-length resource_ids array is replaced by
    its hash. This is deliberately NOT the same shape as the original
    extract_tasks_resource_fm_po_kwargs_hash_idx (1.8GB, zero reads across
    the whole incident that started this redesign): that index hashed the
    ENTIRE composite key into one expression, which only Postgres could use
    if the application queried via that exact expression -- nothing did.
    Here, only the array is hashed; ordinary multi-column WHERE clauses on
    dataset_id/fm_id/po_id still work unchanged, and resource_ids_hash is
    just one more column in an otherwise normal composite index.

    Existing plain `resource_ids = [...]` queries (views.py's get-or-create)
    remain CORRECT after this migration without any code change -- Postgres
    still filters resource_ids as a real column, just via a less-selective
    index prefix (dataset_id, fm_id, po_id) followed by a heap recheck,
    rather than an exact index hit. A later task in this plan updates
    views.py to filter on resource_ids_hash explicitly, restoring
    exact-index-hit performance. bulk_create(ignore_conflicts=True) in
    ingest.py needs no such change -- Postgres enforces uniqueness at
    INSERT time via whatever columns back the constraint, regardless of
    how the INSERT was issued.
    """

    dependencies = [
        ("analytics", "0023_extractdata_composite_pk"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_ADD_HASH_COLUMN_SQL,
            reverse_sql=_REVERSE_ADD_HASH_COLUMN_SQL,
            state_operations=[
                migrations.AddField(
                    model_name="extracttask",
                    name="resource_ids_hash",
                    field=models.GeneratedField(
                        expression=Func(
                            F("resource_ids"),
                            function="extract_tasks_resource_ids_hash",
                        ),
                        output_field=models.IntegerField(),
                        db_persist=True,
                    ),
                ),
            ],
        ),
        migrations.RunSQL(
            sql=_REBUILD_INDEXES_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
