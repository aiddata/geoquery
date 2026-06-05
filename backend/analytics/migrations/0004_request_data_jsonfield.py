from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0003_request_info_textfield'),
    ]

    operations = [
        migrations.AddField(
            model_name='request',
            name='data',
            field=models.JSONField(blank=True, null=True),
        ),
    ]