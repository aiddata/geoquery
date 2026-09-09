import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0019_extractdata_value_arrays"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="extracttaskbuildprogress",
            name="extract_task_build_progress_resource_po_unique",
        ),
        migrations.RemoveField(model_name="extracttaskbuildprogress", name="resource"),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="resource_ids",
            field=django.contrib.postgres.fields.ArrayField(
                models.IntegerField(), default=list
            ),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="extracttaskbuildprogress",
            constraint=models.UniqueConstraint(
                fields=("resource_ids", "po"),
                name="extract_task_build_progress_resource_ids_po_unique",
            ),
        ),
    ]
