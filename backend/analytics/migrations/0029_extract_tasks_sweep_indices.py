from django.db import migrations


# The two hourly maintenance sweeps each ran one unpruned statement over every
# partition of extract_tasks. Measured on production 2026-10-01, at 655M tasks
# and 240 GB:
#
#   free_stale_processing_tasks      mean 815s, max 1063s  -> freed 45 rows
#   manage_processing_task_errors    mean 815s, max 1063s  -> reset 4 rows
#                                                              across 14 runs
#
# Both are a single UPDATE, so each is a single transaction, and under
# transaction pooling that holds a PgBouncer server slot for its entire
# duration (see database.md section 5). They also share a beat tick -- both
# are schedule: 3600 -- so they run concurrently and contend on the same scan,
# which is why their timings match to 0.1s across 13 runs.
#
# The cost scales with the table, not with the work: at the 2.63B-task target
# these become ~40min transactions, at which point they overlap their own
# hourly interval and stranded tasks accumulate faster than they are reaped.
# A request waiting on one stranded claim already spent 63% of its 2h18m
# wall time waiting for the reaper (request fef24b4a / c7501786, same day).
#
# Both predicates match a tiny, bounded population instead:
#
#   status IN (2,3)  is in-flight claim depth = throughput x residence time,
#                    measured at ~112,000 rows with zero older than 30min, so
#                    it is bounded by fleet concurrency and does NOT grow with
#                    the table (~5 MB, flat at full scale);
#   status = -1      is errored tasks awaiting retry, measured at 0-4 rows.
#
# Keyed on update_time and attempts rather than id because that is what each
# sweep filters on after status -- the reaper wants rows older than
# STALE_TASK_MINUTES, and the error sweep wants rows under
# MAX_EXTRACT_TASK_ATTEMPTS. Keying on attempts matters particularly: tasks
# that exhaust their retries stay at status = -1 permanently, so an id-keyed
# index would make the error sweep re-read every exhausted task on every run,
# reintroducing growth in the one place this migration exists to remove it.
#
# CREATE INDEX CONCURRENTLY is rejected outright on a partitioned table
# ("cannot create index on partitioned table ... concurrently"), so the
# online path is the three-step one: an invalid index on ONLY the parent
# (catalog-only, no build), each child built CONCURRENTLY, then ATTACHed.
# The parent index flips to valid automatically once every child is attached.
# Migration 0014 could use plain CONCURRENTLY because it predates the
# partitioning in 0021 -- do not copy it here.
#
# Partitions come from pg_inherits, not a relname LIKE 'extract_tasks_ds%'
# pattern: that pattern silently misses the catch-all extract_tasks_default,
# which holds every dataset created after 0021 ran.

_INDEXES = (
    (
        "extract_tasks_stale_claims_idx",
        "(update_time)",
        "status IN (2, 3)",
    ),
    (
        "extract_tasks_errored_idx",
        "(attempts)",
        "status = -1",
    ),
)

_PARTITIONS_SQL = """
    SELECT c.relname
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    WHERE i.inhparent = 'extract_tasks'::regclass
    ORDER BY c.relname
"""


def _child_index_name(partition, parent_index):
    """Deterministic child name, kept inside PostgreSQL's 63-byte identifier
    limit. Suffix rather than the parent's full name so the longest real case
    (extract_tasks_default + stale_claims) still fits well clear of it."""
    suffix = parent_index.removeprefix("extract_tasks_")
    return f"{partition}_{suffix}"


def create_indexes(apps, schema_editor):
    conn = schema_editor.connection
    with conn.cursor() as cursor:
        cursor.execute(_PARTITIONS_SQL)
        partitions = [r[0] for r in cursor.fetchall()]

    for parent_index, columns, predicate in _INDEXES:
        with conn.cursor() as cursor:
            # ONLY: catalog entry on the parent, marked invalid, no build.
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {parent_index} "
                f"ON ONLY extract_tasks {columns} WHERE {predicate}"
            )

        for partition in partitions:
            child = _child_index_name(partition, parent_index)
            with conn.cursor() as cursor:
                # A CONCURRENTLY build that fails leaves the index behind and
                # marked invalid; IF NOT EXISTS would then skip it forever and
                # ATTACH would keep the parent invalid. Drop any invalid
                # leftover first so a re-run is actually a retry.
                cursor.execute(
                    "SELECT 1 FROM pg_class c "
                    "JOIN pg_index x ON x.indexrelid = c.oid "
                    "WHERE c.relname = %s AND NOT x.indisvalid",
                    [child],
                )
                if cursor.fetchone():
                    cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {child}")

                cursor.execute(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {child} "
                    f"ON {partition} {columns} WHERE {predicate}"
                )
                cursor.execute(
                    f"ALTER INDEX {parent_index} ATTACH PARTITION {child}"
                )


def drop_indexes(apps, schema_editor):
    conn = schema_editor.connection
    # Dropping the parent cascades to every attached child, so the children
    # need no separate handling here.
    for parent_index, _columns, _predicate in _INDEXES:
        with conn.cursor() as cursor:
            cursor.execute(f"DROP INDEX IF EXISTS {parent_index}")


class Migration(migrations.Migration):
    """Partial indexes backing the two hourly extract_tasks maintenance sweeps."""

    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    atomic = False

    dependencies = [
        ("analytics", "0028_extractdata_drop_data_column"),
    ]

    operations = [
        migrations.RunPython(create_indexes, drop_indexes),
    ]
