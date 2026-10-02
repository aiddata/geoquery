from django.db import migrations, models


# Progress and lease columns for block extraction (analytics.blocks). All
# nullable with no default, so each AddField is a catalog-only change -- no
# table rewrite -- on a table of a few thousand rows.


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0028_extractdata_drop_data_column'),
    ]

    operations = [
        migrations.AddField(
            model_name='extracttaskbuildprogress',
            name='computed_up_to_fm_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='extracttaskbuildprogress',
            name='block_claimed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='extracttaskbuildprogress',
            name='block_claim_token',
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
