from django.db import migrations, models


class Migration(migrations.Migration):
    """Add scalar value columns beside the existing arrays.

    ADD COLUMN with no default and NULL allowed has long been a catalog-only
    change in PostgreSQL -- no table rewrite -- so this is effectively instant
    on the 713.7M-row table rather than proportional to its size. (The PG11
    fast path people usually cite is the one for non-null constant DEFAULTs,
    which is a different case and not what this does.)

    It is not lock-free, though: each ADD COLUMN takes ACCESS EXCLUSIVE on the
    partitioned parent and cascades to all 57 partitions, and Django runs all
    three in one transaction, so the lock is held across them until commit.
    At the ~400 inserts/sec this table sees that should resolve in
    milliseconds, but it does briefly block writers -- see 0023 for the same
    consideration on a much heavier ALTER.
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
