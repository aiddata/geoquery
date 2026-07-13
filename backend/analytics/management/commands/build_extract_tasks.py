import time
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import connection

from datasets.models import DatasetResource
from features.models import FeatMap
from analytics.models import ExtractTask, ProcessingOption

logger = getLogger(__name__)


class Command(BaseCommand):
    help = "Create ExtractTask rows for covered dataset/feature pairs that don't have one yet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            default=False,
            help="Whether to overwrite existing extract tasks (not yet implemented)",
        )

    def handle(self, *_args, **_options):
        result = _build_extract_tasks()
        self.stdout.write(self.style.SUCCESS(
            f"Generated {result['added']} new extract tasks in {result['elapsed']:.2f}s"
        ))


def _build_extract_tasks():
    from features.models import Feature
    from datasets.models import Dataset

    if not Feature.objects.exists():
        logger.info("No features found in database")
        return {"added": 0, "elapsed": 0}

    if not Dataset.objects.exists():
        logger.info("No datasets found in database")
        return {"added": 0, "elapsed": 0}

    t_start = time.perf_counter()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                dataset_resources.id AS resource_id,
                feat_map.id AS fm_id,
                processing_options.id AS po_id
            FROM coverage
            INNER JOIN feat_map
                ON coverage.geom_id = feat_map.geom_id
            INNER JOIN feature_collections
                ON feat_map.fc_id = feature_collections.id
            INNER JOIN dataset_resources
                ON coverage.dataset_id = dataset_resources.dataset_id
            INNER JOIN processing_options
                ON coverage.dataset_id = processing_options.dataset_id
            INNER JOIN datasets
                ON coverage.dataset_id = datasets.id
            WHERE coverage.status = 1
            AND processing_options.active = TRUE
            AND feature_collections.active = TRUE
            AND feature_collections.is_user_upload = FALSE
            AND datasets.active = TRUE
            """
        )
        candidates = cursor.fetchall()

    logger.info("Identified %d potential extract tasks", len(candidates))

    added = 0
    for resource_id, fm_id, po_id in candidates:
        if not ExtractTask.objects.filter(resource_id=resource_id, fm_id=fm_id, po_id=po_id).exists():
            ExtractTask.objects.create(
                resource=DatasetResource.objects.get(id=resource_id),
                fm=FeatMap.objects.get(id=fm_id),
                po=ProcessingOption.objects.get(id=po_id),
            )
            added += 1

    elapsed = time.perf_counter() - t_start
    logger.info("Generated %d new extract tasks in %.2fs", added, elapsed)
    return {"added": added, "elapsed": elapsed}