from django.db import migrations


class Migration(migrations.Migration):
    """
    Partial index backing the two hot reads on the pending queue:

    - the dispatch claim in analytics.tasks.processing.claim_pending_tasks,
      which runs once per completed extract task and wants the single
      highest-priority, oldest pending row -- now a one-probe index walk
      instead of a parallel seq scan and sort over the whole table;
    - the pending-count query the KEDA autoscaler polls, which becomes an
      index-only scan over exactly the pending rows.

    Restricted to status = 0 so it stays small: pending rows are the only ones
    either reader ever looks at, and the index shrinks on its own as the
    backlog drains. Built CONCURRENTLY so the 128 worker slots keep claiming
    while it builds, which is why the migration is non-atomic.
    """

    atomic = False

    dependencies = [
        ("analytics", "0013_extracttask_index_cleanup"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS extract_tasks_pending_idx "
                "ON extract_tasks (priority DESC, submit_time ASC) WHERE status = 0;"
            ),
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS extract_tasks_pending_idx;",
        ),
    ]
