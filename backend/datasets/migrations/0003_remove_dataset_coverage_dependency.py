from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0002_alter_dataset_name"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="dataset",
            name="coverage_dependency",
        ),
    ]