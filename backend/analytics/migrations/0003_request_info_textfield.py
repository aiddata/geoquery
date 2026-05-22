from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0002_request_comments_requested_request_contact_flag'),
    ]

    operations = [
        migrations.AlterField(
            model_name='request',
            name='info',
            field=models.TextField(blank=True, null=True),
        ),
    ]
