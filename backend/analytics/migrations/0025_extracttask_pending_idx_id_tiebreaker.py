from django.db import migrations


# extract_tasks_pending_idx backs claim_pending_tasks' SELECT ... FOR UPDATE
# SKIP LOCKED ... ORDER BY priority DESC, submit_time ASC, id ASC LIMIT %s
# (processing.py). Rebuilding it here to include id as a third column keeps
# that query servable by an index-only scan of this partial index -- without
# id here, the added `, id ASC` in the query's ORDER BY would still be
# correct, but Postgres would need an extra sort step (or a less selective
# scan) to satisfy it instead of walking the index directly in the exact
# order the query wants.
#
# Not built CONCURRENTLY: unsupported directly on a partitioned table
# (Postgres requires the per-partition CONCURRENTLY-then-ATTACH dance
# instead -- see migration 0022's docstring for the same constraint). This
# DROP+CREATE takes a lock across a now much-larger status=0 population than
# migration 0022's empty-table build, unlike that one -- benchmark against a
# prod-sized copy and prefer a lower-traffic window, same caveat as
# migrations 0023/0024.
_FORWARD_SQL = """
    DROP INDEX IF EXISTS extract_tasks_pending_idx;
    CREATE INDEX extract_tasks_pending_idx
        ON extract_tasks (priority DESC, submit_time, id)
        WHERE status = 0;
"""

_REVERSE_SQL = """
    DROP INDEX IF EXISTS extract_tasks_pending_idx;
    CREATE INDEX extract_tasks_pending_idx
        ON extract_tasks (priority DESC, submit_time)
        WHERE status = 0;
"""


class Migration(migrations.Migration):
    """
    Adds id as a third column to extract_tasks_pending_idx, matching the
    id ASC tiebreaker added to claim_pending_tasks' ORDER BY in processing.py.

    Root cause this closes: build_extract_tasks inserts in large batches
    sharing one NOW() per INSERT, so many rows can carry the exact same
    (priority, submit_time). Without id as a tiebreaker, concurrent
    SELECT ... FOR UPDATE SKIP LOCKED claims have no stable order to
    partition across a large tied group of rows -- concurrent claimers
    circle the same ambiguous block instead of cleanly dividing sequential
    work, and skip-distance grows with the tied-group size, not just
    concurrency. Observed in production: throughput collapsed from ~130/s
    to ~2-3/s once the pending backlog grew large enough, independent of how
    many worker replicas were running -- confirming the bottleneck was tied-
    row scan inefficiency, not worker concurrency itself.
    """

    dependencies = [
        ("analytics", "0024_extracttask_resource_ids_hash"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
