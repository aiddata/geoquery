from django.db import migrations


class Migration(migrations.Migration):
    """
    Clears extract_tasks/extract_data/request_map and the build-progress
    tracking tables ahead of the schema redesign in later migrations
    (resource_ids arrays, partitioning, new indexes). Per user decision:
    wiping this data is acceptable -- it's regenerable via build_extract_tasks
    + run_extract_task, and the incident-scale volume already in these tables
    (tens of millions of rows, mid-rebuild) isn't worth preserving through a
    structural rewrite.
    """

    dependencies = [
        ("analytics", "0016_extracttaskbuildrun"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                TRUNCATE TABLE
                    extract_data,
                    request_map,
                    extract_tasks,
                    extract_task_build_progress
                RESTART IDENTITY CASCADE;
                UPDATE extract_task_build_run SET in_progress = FALSE, last_progress_at = NULL WHERE id = 1;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
