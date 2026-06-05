"""Utilities for managing the pre-simplified geometry materialized views
used by the vector tile endpoint. These views are created by migration 0002
and should be refreshed after any boundary data changes (e.g., after ingest)."""

from django.db import connection
from loguru import logger

MATERIALIZED_VIEWS = [
    "features_simplified_z0_5",
    "features_simplified_z6_9",
    "features_simplified_z10_12",
]


def refresh_materialized_views():
    """Refresh all simplified-geometry materialized views."""
    with connection.cursor() as cursor:
        for view_name in MATERIALIZED_VIEWS:
            logger.info(f"Refreshing materialized view: {view_name}")
            cursor.execute(f"REFRESH MATERIALIZED VIEW {view_name}")
            logger.info(f"  Done: {view_name}")
