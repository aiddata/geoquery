from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('datasets', '0003_remove_dataset_coverage_dependency'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataset',
            name='short_name',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
