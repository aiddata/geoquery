from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0006_requesttoken"),
    ]

    operations = [
        migrations.AlterField(
            model_name="requesttoken",
            name="email",
            field=models.EmailField(db_index=True),
        ),
    ]