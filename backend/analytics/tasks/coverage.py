import logging
import time

from analytics.models import Coverage
from celery import group, shared_task
from django.db import connection

logger = logging.getLogger(__name__)


def create_coverage_records_for_dataset(dataset_id):
    """Insert coverage rows (status=-1) for a dataset against all existing features."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO coverage (geom_id, dataset_id, status)
            SELECT f.id, %s, -1
            FROM features f
            WHERE NOT EXISTS (
                SELECT 1 FROM coverage c WHERE c.geom_id = f.id AND c.dataset_id = %s
            )
            """,
            [dataset_id, dataset_id],
        )
        created = cursor.rowcount
    logger.info("Created %d coverage records for dataset %s", created, dataset_id)
    return created


def create_coverage_records_for_feature(feature_id):
    """Insert coverage rows (status=-1) for a feature against all existing datasets."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO coverage (geom_id, dataset_id, status)
            SELECT %s, d.id, -1
            FROM datasets d
            WHERE NOT EXISTS (
                SELECT 1 FROM coverage c WHERE c.geom_id = %s AND c.dataset_id = d.id
            )
            """,
            [feature_id, feature_id],
        )
        created = cursor.rowcount
    logger.info("Created %d coverage records for feature %s", created, feature_id)
    return created


def create_missing_coverage_records():
    t_start = time.perf_counter()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO coverage (geom_id, dataset_id, status)
            SELECT f.id, d.id, -1
            FROM features f
            CROSS JOIN datasets d
            LEFT JOIN coverage c ON c.geom_id = f.id AND c.dataset_id = d.id
            WHERE c.geom_id IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM feat_map fm
                JOIN feature_collections fc ON fm.fc_id = fc.id
                WHERE fm.geom_id = f.id AND fc.is_user_upload = TRUE
            )
            ON CONFLICT DO NOTHING
            """
        )
        created = cursor.rowcount

    elapsed = time.perf_counter() - t_start
    logger.info("Inserted %d coverage records in %.2fs", created, elapsed)
    return {"created": created}


def run_missing_coverage_checks(sync=False):
    t_start = time.perf_counter()

    untested_dataset_ids = list(
        Coverage.objects.filter(status=-1)
        .values_list("dataset_id", flat=True)
        .distinct()
    )

    if not untested_dataset_ids:
        logger.info("No untested coverage records to process")
        return

    for did in untested_dataset_ids:
        if sync:
            result = test_coverage_for_dataset(did)
            logger.info(
                f"Dataset {did}: {result['covered']} covered, {result['not_covered']} not covered"
            )
        else:
            test_coverage_for_dataset.delay(did)
            logger.info(f"Dispatched coverage check for dataset {did}")

    elapsed = time.perf_counter() - t_start
    logger.info(f"Coverage checking completed/dispatched in {elapsed:.2f}s")


def test_single_coverage_record(feature_id, dataset_id):
    """Test coverage for a single feature-dataset pair."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE coverage
            SET status = CASE
                WHEN ST_Contains(
                    (SELECT spatial_extent FROM datasets WHERE id = %s),
                    (SELECT shape FROM features WHERE id = %s)
                ) THEN 1
                ELSE 0
            END
            WHERE geom_id = %s AND dataset_id = %s AND status = -1
            RETURNING status;
            """,
            [dataset_id, feature_id, feature_id, dataset_id],
        )
        row = cursor.fetchone()

    if row is None:
        logger.warning(
            "No coverage record found for feature %s and dataset %s",
            feature_id,
            dataset_id,
        )
        return None

    status = row[0]
    logger.info(
        "Coverage tested for feature %s and dataset %s: status=%d",
        feature_id,
        dataset_id,
        status,
    )
    return {"feature_id": feature_id, "dataset_id": dataset_id, "status": status}


def _test_coverage_for_feature(feature_id):
    """Test coverage for a single feature against all datasets.

    Checks whether the feature falls within the spatial extent of each dataset
    using ST_Contains. Sets coverage status to 1 (covered) or 0 (not covered).
    Only operates on records with status = -1 (untested).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH updated AS (
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
                RETURNING status
            )
            SELECT
                COUNT(*) FILTER (WHERE status = 1),
                COUNT(*) FILTER (WHERE status = 0)
            FROM updated
            """,
            [feature_id, feature_id],
        )
        covered, not_covered = cursor.fetchone()

    logger.info(
        "Coverage tested for feature %s: %d covered, %d not covered",
        feature_id,
        covered,
        not_covered,
    )
    return {
        "feature_id": feature_id,
        "updated": covered + not_covered,
        "covered": covered,
        "not_covered": not_covered,
    }


@shared_task
def test_coverage_for_feature(feature_id):
    return _test_coverage_for_feature(feature_id)


_DISPATCH_BATCH_SIZE = 500


@shared_task
def test_coverage_for_feature_collection(feature_collection_id):
    dispatched = 0
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT geom_id FROM feat_map WHERE fc_id = %s",
            [feature_collection_id],
        )
        batch = cursor.fetchmany(_DISPATCH_BATCH_SIZE)
        while batch:
            group(test_coverage_for_feature.s(row[0]) for row in batch).delay()
            dispatched += len(batch)
            batch = cursor.fetchmany(_DISPATCH_BATCH_SIZE)

    if not dispatched:
        logger.warning("No features found for collection %s", feature_collection_id)
    else:
        logger.info(
            "Dispatched coverage tasks for %d features in collection %s",
            dispatched,
            feature_collection_id,
        )
    return {"feature_collection_id": feature_collection_id, "dispatched": dispatched}


@shared_task
def test_coverage_for_dataset(dataset_id):
    """Test spatial coverage for a single dataset against all features.

    Checks whether each feature falls within the dataset's spatial extent
    using ST_Contains. Sets coverage status to 1 (covered) or 0 (not covered).
    Only operates on records with status = -1 (untested).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH updated AS (
                UPDATE coverage
                SET status = CASE
                    WHEN geom_id = ANY(
                        SELECT features.id
                        FROM datasets
                        JOIN features ON ST_Contains(datasets.spatial_extent, features.shape)
                        WHERE datasets.id = %s
                    ) THEN 1
                    ELSE 0
                END
                WHERE dataset_id = %s AND status = -1
                RETURNING status
            )
            SELECT
                COUNT(*) FILTER (WHERE status = 1),
                COUNT(*) FILTER (WHERE status = 0)
            FROM updated
            """,
            [dataset_id, dataset_id],
        )
        covered, not_covered = cursor.fetchone()

    logger.info(
        "Coverage tested for dataset %s: %d covered, %d not covered",
        dataset_id,
        covered,
        not_covered,
    )
    return {
        "dataset_id": dataset_id,
        "updated": covered + not_covered,
        "covered": covered,
        "not_covered": not_covered,
    }
