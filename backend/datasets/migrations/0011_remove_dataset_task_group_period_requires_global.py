from django.db import migrations, models


class Migration(migrations.Migration):
    """Allow grouped non-global datasets.

    The constraint existed because build_extract_tasks only grouped resources
    on its global branch, so a grouped non-global dataset silently got no
    tasks. Pair sync (analytics.sync) groups every dataset the same way and
    coverage gates non-global ones per feature, so the combination is now
    supported.
    """

    dependencies = [
        ("datasets", "0010_dataset_license_dataset_license_url"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="dataset",
            name="dataset_task_group_period_requires_global",
        ),
        migrations.AlterField(
            model_name="dataset",
            name="task_group_period",
            field=models.CharField(
                blank=True,
                choices=[
                    ("day", "Day"),
                    ("week", "Week"),
                    ("month", "Month"),
                    ("quarter", "Quarter"),
                    ("year", "Year"),
                ],
                help_text=(
                    "If set, background extraction groups this dataset's resources into "
                    "one task per UTC date_trunc(task_group_period, temporal) bucket per "
                    "feature/po, instead of one task per resource. Every resource then "
                    "needs a temporal value. Null = standard (one task per resource)."
                ),
                max_length=10,
                null=True,
            ),
        ),
    ]
