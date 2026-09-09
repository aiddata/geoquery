import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0018_extracttask_resource_ids"),
    ]

    operations = [
        migrations.RemoveField(model_name="extractdata", name="float_value"),
        migrations.RemoveField(model_name="extractdata", name="int_value"),
        migrations.RemoveField(model_name="extractdata", name="str_value"),
        migrations.AddField(
            model_name="extractdata",
            name="float_values",
            field=django.contrib.postgres.fields.ArrayField(
                models.FloatField(null=True), blank=True, null=True
            ),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="int_values",
            field=django.contrib.postgres.fields.ArrayField(
                models.BigIntegerField(null=True), blank=True, null=True
            ),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="str_values",
            field=django.contrib.postgres.fields.ArrayField(
                models.CharField(max_length=100, null=True), blank=True, null=True
            ),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="dataset_id",
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
    ]
