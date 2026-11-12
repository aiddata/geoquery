"""Title every geoBoundaries ADM0 "(Country)".

0015 suffixed ADM0 titles with their boundaryCanonical, which for ADM0 is the
country's formal name ("Republic of Fiji") rather than a unit type like the
other levels' ("Districts"). Every ADM0 is now "(Country)", as the ingest
command titles them (``collection_title`` in ingest_geoboundaries).

The suffix 0015 added is replaced; an ADM0 without one gets "(Country)"
appended. Titles feed no capture trigger, so nothing is invalidated. Safe to
run again. The reverse restores 0015's suffix.
"""

import importlib

from django.db import migrations

_0015 = importlib.import_module("features.migrations.0015_geoboundaries_canonical_titles")
_PREVIOUS = _0015._SUFFIX
_ADM0 = "name LIKE 'gB\\_%' AND other->>'boundaryType' = 'ADM0'"

FORWARD = f"""
UPDATE feature_collections
SET title = CASE
        WHEN right(title, length({_PREVIOUS})) = {_PREVIOUS}
            THEN left(title, length(title) - length({_PREVIOUS}))
        ELSE title
    END || ' (Country)'
WHERE {_ADM0} AND right(title, length(' (Country)')) <> ' (Country)';
"""

REVERSE = f"""
UPDATE feature_collections
SET title = left(title, length(title) - length(' (Country)'))
    || coalesce({_PREVIOUS}, '')
WHERE {_ADM0} AND right(title, length(' (Country)')) = ' (Country)';
"""


class Migration(migrations.Migration):
    dependencies = [("features", "0015_geoboundaries_canonical_titles")]

    operations = [migrations.RunSQL(FORWARD, reverse_sql=REVERSE)]
