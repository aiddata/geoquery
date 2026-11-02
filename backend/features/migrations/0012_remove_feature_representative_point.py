import importlib

from django.contrib.postgres.operations import RemoveIndexConcurrently
from django.db import migrations

# representative_point was added (0009) to anchor point clustering in vector
# tiles. Tiles are drawn in EPSG:3857 and filtered by collection, so the
# clusters read features_points (0013) instead: one 3857 point per feat_map
# row, behind a GIST (fc_id, pt) index. A 4326 point on `features`, with no
# fc_id, could serve neither the projection nor the collection filter.
#
# The reverse restores 0009's column, trigger and index, then backfills.
_m0009 = importlib.import_module("features.migrations.0009_feature_representative_point")


class Migration(migrations.Migration):
    # DROP INDEX CONCURRENTLY cannot run inside a transaction block, and the
    # reverse backfill commits in batches.
    atomic = False

    dependencies = [
        ('features', '0011_simplified_fc_shape_gist'),
    ]

    operations = [
        # Forward: nothing. Reverse: runs last, once the column, index and
        # trigger are back.
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=_m0009.backfill_representative_point,
        ),
        # The trigger writes the column, so it goes before the column does.
        migrations.RunSQL(
            sql=_m0009.DROP_TRIGGER_SQL,
            reverse_sql=_m0009.CREATE_TRIGGER_SQL,
        ),
        RemoveIndexConcurrently(
            model_name='feature',
            name='idx_features_repr_point',
        ),
        # Drops the column without rewriting the table.
        migrations.RemoveField(
            model_name='feature',
            name='representative_point',
        ),
    ]
