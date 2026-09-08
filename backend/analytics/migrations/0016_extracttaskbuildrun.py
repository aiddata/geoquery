from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Singleton table coordinating parallel build_extract_tasks workers so the
    daily beat schedule can't pile up a fresh wave of workers on top of one
    still grinding through the backlog -- the same "unbounded daily pileup"
    pattern that caused the original extract_tasks bloat incident, just at
    the task-dispatch level instead of the transaction level.

    in_progress + last_progress_at is a heartbeat, not a fixed timeout: any
    worker batch refreshes last_progress_at, so the launcher can tell "still
    actively working through a big backlog" (frequent heartbeat) apart from
    "workers died silently" (stale heartbeat) without needing to guess how
    long the whole backlog should take.
    """

    dependencies = [
        ("analytics", "0015_merge_20260908"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExtractTaskBuildRun",
            fields=[
                ("id", models.SmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("in_progress", models.BooleanField(default=False)),
                ("last_progress_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "extract_task_build_run",
            },
        ),
        migrations.RunSQL(
            sql="INSERT INTO extract_task_build_run (id, in_progress) VALUES (1, FALSE);",
            reverse_sql="DELETE FROM extract_task_build_run WHERE id = 1;",
        ),
    ]
