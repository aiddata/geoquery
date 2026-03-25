import logging

from celery import shared_task
from django.db import connection

logger = logging.getLogger(__name__)


@shared_task
def test_coverage_for_dataset(dataset_id):
    """Test spatial coverage for a single dataset against all features.

    For each feature, checks whether it falls within the dataset's spatial extent
    using ST_Contains. Sets coverage status to 1 (covered) or 0 (not covered).
    Only operates on records with status = -1 (untested).
    """
    logger.info("Testing coverage for dataset %s", dataset_id)

    with connection.cursor() as cursor:
        # Set status=1 for features contained within the dataset's spatial extent
        cursor.execute(
            """
            UPDATE coverage
            SET status = 1
            WHERE dataset_id = %s AND geom_id = ANY(
                SELECT features.id
                FROM datasets
                JOIN features ON ST_Contains(datasets.spatial_extent, features.shape)
                WHERE datasets.id = %s
            );
            """,
            [dataset_id, dataset_id],
        )
        matched = cursor.rowcount

        # Set status=0 for remaining untested records for this dataset
        cursor.execute(
            """
            UPDATE coverage
            SET status = 0
            WHERE dataset_id = %s AND status = -1;
            """,
            [dataset_id],
        )
        unmatched = cursor.rowcount

    logger.info(
        "Dataset %s: %d covered, %d not covered", dataset_id, matched, unmatched
    )
    return {"dataset_id": dataset_id, "covered": matched, "not_covered": unmatched}
