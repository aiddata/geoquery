from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """
    Adds extract_task_build_progress, used by the rewritten build_extract_tasks
    to resume global-dataset task generation per (resource, po) pair instead of
    re-scanning the full candidate space (up to ~12 billion rows) every run.
    See models.py for the full rationale.
    """

    dependencies = [
        ("analytics", "0013_extracttask_index_cleanup"),
        ("datasets", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExtractTaskBuildProgress",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("completed_up_to_fm_id", models.IntegerField(blank=True, null=True)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "resource",
                    models.ForeignKey(
                        db_column="resource_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="datasets.datasetresource",
                    ),
                ),
                (
                    "po",
                    models.ForeignKey(
                        db_column="po_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="analytics.processingoption",
                    ),
                ),
            ],
            options={
                "db_table": "extract_task_build_progress",
            },
        ),
        migrations.AddConstraint(
            model_name="extracttaskbuildprogress",
            constraint=models.UniqueConstraint(
                fields=("resource", "po"),
                name="extract_task_build_progress_resource_po_unique",
            ),
        ),
    ]
