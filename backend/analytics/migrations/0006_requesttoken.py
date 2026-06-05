from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0005_remove_request_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="RequestToken",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("email", models.EmailField(unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
            ],
            options={"db_table": "request_tokens"},
        ),
    ]
