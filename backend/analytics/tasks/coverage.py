import logging

from celery import group, shared_task
from django.db import connection

logger = logging.getLogger(__name__)


def _test_coverage_for_feature(feature_id):
    """Test coverage for a single feature against all datasets.

    Checks whether the feature falls within the spatial extent of each dataset
    using ST_Contains. Sets coverage status to 1 (covered) or 0 (not covered).
    Only operates on records with status = -1 (untested).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE coverage
            SET status = CASE
                WHEN dataset_id = ANY(
                    SELECT datasets.id
                    FROM datasets
                    JOIN features ON ST_Contains(datasets.spatial_extent, features.shape)
                    WHERE features.id = %s
                ) THEN 1
                ELSE 0
            END
            WHERE geom_id = %s AND status = -1
            RETURNING dataset_id, status;
            """,
            [feature_id, feature_id],
        )
        rows = cursor.fetchall()


    covered = [dataset_id for dataset_id, status in rows if status == 1]
    not_covered = [dataset_id for dataset_id, status in rows if status == 0]
    logger.info("Coverage tested for feature %s (%d records updated). covered: %s, not covered: %s", feature_id, len(rows), covered, not_covered)
    return {
        "feature_id": feature_id,
        "updated": len(rows),
        "covered": len(covered),
        "not_covered": len(not_covered),
    }


@shared_task
def test_coverage_for_feature(feature_id):
    return _test_coverage_for_feature(feature_id)


@shared_task
def test_coverage_for_feature_collection(feature_collection_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT geom_id FROM feat_map WHERE fc_id = %s",
            [feature_collection_id],
        )
        feature_ids = [row[0] for row in cursor.fetchall()]

    if not feature_ids:
        logger.warning("No features found for collection %s", feature_collection_id)
        return {"feature_collection_id": feature_collection_id, "dispatched": 0}

    job = group(test_coverage_for_feature.s(fid) for fid in feature_ids)
    job.delay()

    logger.info(
        "Dispatched coverage tasks for %d features in collection %s",
        len(feature_ids),
        feature_collection_id,
    )
    return {"feature_collection_id": feature_collection_id, "dispatched": len(feature_ids)}


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
            WHERE status = -1 AND dataset_id = %s AND geom_id = ANY(
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
