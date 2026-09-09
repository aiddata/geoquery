import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0017_wipe_extract_tasks_for_redesign"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="extracttask",
            name="resource",
        ),
        migrations.AddField(
            model_name="extracttask",
            name="resource_ids",
            field=django.contrib.postgres.fields.ArrayField(
                models.IntegerField(), default=list, size=None
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="extracttask",
            name="dataset_id",
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="extracttask",
            name="task_group_period",
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
    ]
