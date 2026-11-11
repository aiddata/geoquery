"""Add the unit type to geoBoundaries collection titles.

"geoBoundaries v6 - Ghana ADM2" becomes "geoBoundaries v6 - Ghana ADM2
(Districts)", from the boundary metadata's boundaryCanonical, which is kept
in the collection's ``other``. Values naming no unit type are skipped: empty,
"Unknown", "nan", and "gbOpen" (the release family, filled in where the name
was missing); an ADM0 with one of those is "Country". The ingest command
builds titles the same way (``collection_title`` in ingest_geoboundaries).

A title is display text: no capture trigger reads it, so nothing is
invalidated or recomputed. Collections already carrying the suffix are left
alone, so the migration can run again. The reverse strips the suffix.
"""

from django.db import migrations

_CANONICAL = """
    CASE
        WHEN coalesce(lower(btrim(other->>'boundaryCanonical')), '')
             NOT IN ('', 'unknown', 'gbopen', 'nan')
            THEN btrim(other->>'boundaryCanonical')
        WHEN other->>'boundaryType' = 'ADM0' THEN 'Country'
    END
"""
_ELIGIBLE = f"name LIKE 'gB\\_%' AND ({_CANONICAL}) IS NOT NULL"
_SUFFIX = f"' (' || ({_CANONICAL}) || ')'"

FORWARD = f"""
UPDATE feature_collections
SET title = title || {_SUFFIX}
WHERE {_ELIGIBLE} AND right(title, length({_SUFFIX})) <> {_SUFFIX};
"""

REVERSE = f"""
UPDATE feature_collections
SET title = left(title, length(title) - length({_SUFFIX}))
WHERE {_ELIGIBLE} AND right(title, length({_SUFFIX})) = {_SUFFIX};
"""


class Migration(migrations.Migration):
    dependencies = [("features", "0014_features_cluster_points")]

    operations = [migrations.RunSQL(FORWARD, reverse_sql=REVERSE)]
