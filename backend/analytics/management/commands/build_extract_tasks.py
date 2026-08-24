import time
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import connection


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
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {result['added']} new extract tasks in {result['elapsed']:.2f}s"
            )
        )


def _build_extract_tasks():
    t_start = time.perf_counter()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO extract_tasks
                (resource_id, fm_id, po_id, status, priority, attempts, submit_time)
            SELECT
                dr.id,
                fm.id,
                po.id,
                0, 0, 0, NOW()
            FROM coverage
            INNER JOIN feat_map fm
                ON coverage.geom_id = fm.geom_id
            INNER JOIN feature_collections fc
                ON fm.fc_id = fc.id
            INNER JOIN dataset_resources dr
                ON coverage.dataset_id = dr.dataset_id
            INNER JOIN processing_options po
                ON coverage.dataset_id = po.dataset_id
            INNER JOIN datasets d
                ON coverage.dataset_id = d.id
            WHERE coverage.status = 1
              AND po.active = TRUE
              AND fc.active = TRUE
              AND fc.is_user_upload = FALSE
              AND d.active = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM extract_tasks et
                  WHERE et.resource_id = dr.id
                    AND et.fm_id = fm.id
                    AND et.po_id = po.id
              )
            """
        )
        added = cursor.rowcount

    elapsed = time.perf_counter() - t_start
    logger.info("Generated %d new extract tasks in %.2fs", added, elapsed)
    return {"added": added, "elapsed": elapsed}
