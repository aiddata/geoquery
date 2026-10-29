from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations

# Tile queries filter on both fc_id and the tile envelope. With only separate
# fc_id (btree) and shape (GiST) indexes, the planner ANDs the two bitmaps, and
# the shape side first collects every feature in the envelope from every
# collection: 780k rows for one z2 tile on production, 108 ms spent proving an
# empty tile empty. A composite index finds only the selected collections'
# features (2.6 ms for the same tile), for one fc_id or an fc_id = ANY(...)
# list alike.
#
# The existing {table}_fc_id_idx stays: matviews.py deletes by fc_id and
# mcp_server.data.geometry looks rows up by fc_id + geom_id.
_TABLES = (
    "features_simplified_z0_5",
    "features_simplified_z6_9",
    "features_simplified_z10_12",
)


def _index_name(table):
    return f"{table}_fc_id_shape_idx"


def create_indexes(apps, schema_editor):
    conn = schema_editor.connection
    for table in _TABLES:
        index = _index_name(table)
        with conn.cursor() as cursor:
            # A CONCURRENTLY build that fails leaves the index behind, marked
            # invalid; IF NOT EXISTS would then skip it forever. Drop any
            # invalid leftover first so a re-run is actually a retry.
            cursor.execute(
                "SELECT 1 FROM pg_class c "
                "JOIN pg_index x ON x.indexrelid = c.oid "
                "WHERE c.relname = %s AND NOT x.indisvalid",
                [index],
            )
            if cursor.fetchone():
                cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index}")

            cursor.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index} "
                f"ON {table} USING GIST (fc_id, shape)"
            )


def drop_indexes(apps, schema_editor):
    conn = schema_editor.connection
    for table in _TABLES:
        with conn.cursor() as cursor:
            cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_index_name(table)}")


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block. It
    # holds no write lock, so ingest and simplified-geometry rebuilds keep
    # running while the indexes build.
    atomic = False

    dependencies = [
        ('features', '0010_feat_map_name_search'),
    ]

    operations = [
        # Trusted extension (PG13+), so the database owner can create it
        # without superuser. Provides the btree operator class for fc_id.
        BtreeGistExtension(),
        migrations.RunPython(create_indexes, drop_indexes),
    ]
