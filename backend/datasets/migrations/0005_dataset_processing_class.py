from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('datasets', '0004_dataset_short_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataset',
            name='processing_class',
            field=models.CharField(default='zonal_stats', max_length=50),
        ),
    ]
