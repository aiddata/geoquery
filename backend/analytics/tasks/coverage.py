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
    # Find all (feature, dataset) pairs that don't yet have a coverage record
    t_start = time.perf_counter()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT f.id AS geom_id, d.id AS dataset_id
            FROM features f
            CROSS JOIN datasets d
            LEFT JOIN coverage c ON c.geom_id = f.id AND c.dataset_id = d.id
            WHERE (c.geom_id IS NULL OR c.status = -1)
            AND NOT EXISTS (
                SELECT 1 FROM feat_map fm
                JOIN feature_collections fc ON fm.fc_id = fc.id
                WHERE fm.geom_id = f.id AND fc.is_user_upload = TRUE
            )
            """
        )
        missing_pairs = cursor.fetchall()

    if not missing_pairs:
        logger.info("No missing coverage records")
    else:
        records = [
            Coverage(geom_id=geom_id, dataset_id=dataset_id, status=-1)
            for geom_id, dataset_id in missing_pairs
        ]
        Coverage.objects.bulk_create(records, ignore_conflicts=True)

        elapsed = time.perf_counter() - t_start
        logger.info("Inserted %d coverage records in %.2f}s", len(records), elapsed)

    return {"created": len(records)}


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
                logger.info(f"Dataset {did}: {result['covered']} covered, {result['not_covered']} not covered")
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
        logger.warning("No coverage record found for feature %s and dataset %s", feature_id, dataset_id)
        return None

    status = row[0]
    logger.info("Coverage tested for feature %s and dataset %s: status=%d", feature_id, dataset_id, status)
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

    Checks whether each feature falls within the dataset's spatial extent
    using ST_Contains. Sets coverage status to 1 (covered) or 0 (not covered).
    Only operates on records with status = -1 (untested).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
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
            RETURNING geom_id, status;
            """,
            [dataset_id, dataset_id],
        )
        rows = cursor.fetchall()

    covered = [geom_id for geom_id, status in rows if status == 1]
    not_covered = [geom_id for geom_id, status in rows if status == 0]
    logger.info(
        "Coverage tested for dataset %s (%d records updated). covered: %s, not covered: %s",
        dataset_id, len(rows), covered, not_covered,
    )
    return {
        "dataset_id": dataset_id,
        "updated": len(rows),
        "covered": len(covered),
        "not_covered": len(not_covered),
    }
