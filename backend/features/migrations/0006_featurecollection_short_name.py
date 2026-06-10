from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('features', '0005_user_upload_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='featurecollection',
            name='short_name',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
