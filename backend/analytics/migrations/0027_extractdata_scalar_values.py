from django.db import migrations, models


class Migration(migrations.Migration):
    """Add scalar value columns beside the existing arrays.

    ADD COLUMN with no default and NULL allowed is a catalog-only change in
    PostgreSQL 11+, so this is instant on the 713.7M-row partitioned table
    rather than a rewrite. It cascades to all 57 partitions automatically.
    """

    dependencies = [
        ("analytics", "0026_alter_extracttaskbuildprogress_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="extractdata",
            name="int_value",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="float_value",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="str_value",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
