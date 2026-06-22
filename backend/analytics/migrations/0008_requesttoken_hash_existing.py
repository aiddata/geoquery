from django.db import migrations


def clear_plaintext_tokens(apps, schema_editor):
    # Existing tokens are stored as plaintext and cannot be converted to hashes
    # without the original raw value. Clear them so stale links fail cleanly.
    RequestToken = apps.get_model("analytics", "RequestToken")
    RequestToken.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0007_remove_requesttoken_email_unique"),
    ]

    operations = [
        migrations.RunPython(clear_plaintext_tokens, migrations.RunPython.noop),
    ]
