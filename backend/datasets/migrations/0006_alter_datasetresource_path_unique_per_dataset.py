from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('datasets', '0005_dataset_processing_class'),
    ]

    operations = [
        # Drop the global UNIQUE on path: it is relative to each dataset's own
        # path (e.g. "." for single-file datasets), so it is only meaningful
        # within a dataset, not globally.
        migrations.AlterField(
            model_name='datasetresource',
            name='path',
            field=models.CharField(max_length=200),
        ),
        # Enforce uniqueness per dataset instead.
        migrations.AddConstraint(
            model_name='datasetresource',
            constraint=models.UniqueConstraint(
                fields=('dataset', 'path'),
                name='unique_dataset_resource_path',
            ),
        ),
    ]
