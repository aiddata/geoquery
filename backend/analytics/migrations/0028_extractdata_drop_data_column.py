from django.db import migrations


class Migration(migrations.Migration):
    """Drop the data_column discriminator.

    Redundant now that each type has its own column on both the scalar and
    array side: the type is whichever column is non-NULL, and nothing needs
    the type of a NULL value -- every reader skips NULLs regardless.

    DROP COLUMN is catalog-only in PostgreSQL; it marks the attribute dropped
    rather than rewriting the table, so the 4-6 bytes per row are not
    reclaimed until the rows are rewritten. That is immaterial here because
    reset_extract_data truncates the table outright at cutover.

    Like 0027 this takes ACCESS EXCLUSIVE on the partitioned parent and
    cascades to all 57 partitions, held until the migration transaction
    commits -- brief, but it does block writers.
    """

    dependencies = [
        ("analytics", "0027_extractdata_scalar_values"),
    ]

    operations = [
        migrations.RemoveField(model_name="extractdata", name="data_column"),
    ]
