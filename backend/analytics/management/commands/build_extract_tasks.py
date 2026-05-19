import time

from django.core.management.base import BaseCommand
from django.db import connection

from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ExtractTask, ProcessingOption


class Command(BaseCommand):
    help = "Handles the generation of extract tasks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            default=False,
            help="Whether to overwrite existing extract tasks (not yet implemented)",
        )

    def handle(self, *args, **options):
        if not Feature.objects.exists():
            self.stdout.write("No features found in database")
            return

        if not Dataset.objects.exists():
            self.stdout.write("No datasets with coverage available were found in database")
            return

        # Find all (feature, dataset) pairs that don't yet have a extract task
        t_start = time.perf_counter()

        # INSERT INTO extract_tasks (resource_id, fm_id, po_id)
        select_task_query = """
            SELECT
                dataset_resources.id AS resource_id,
                coverage.geom_id AS fm_id,
                processing_options.id AS po_id
            FROM coverage
            LEFT OUTER JOIN dataset_resources
                ON coverage.dataset_id = dataset_resources.dataset_id
            LEFT OUTER JOIN processing_options
                ON coverage.dataset_id = processing_options.dataset_id
            LEFT OUTER JOIN datasets
                ON coverage.dataset_id = datasets.id
            LEFT OUTER JOIN feat_map
                ON coverage.geom_id = feat_map.geom_id
            LEFT OUTER JOIN feature_collections
                ON feat_map.fc_id = feature_collections.id
            WHERE coverage.status = 1
            AND processing_options.active = TRUE
            AND feature_collections.active = TRUE
            AND datasets.active = TRUE
            ;
        """
        # ON CONFLICT (resource_id, fm_id, po_id)
        # DO NOTHING
        # RETURNING id

        result = None
        with connection.cursor() as cursor:
            # if overwrite:
            #     cur.execute("DELETE FROM extract_tasks;")
            cursor.execute(select_task_query)
            result = cursor.fetchall()
            count_extracts = len(result)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Identified {count_extracts} available extract tasks to generate"
                )
            )

        for et in result:
            new_task = ExtractTask(
                resource=DatasetResource.objects.get(id=et[0]),
                fm=FeatMap.objects.get(id=et[1]),
                po=ProcessingOption.objects.get(id=et[2])
            )
            new_task.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created extract task for resource {et[0]}, feature {et[1]}, processing option {et[2]}"
                )
            )

        t_end = time.perf_counter()
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {count_extracts} extract tasks in {t_end - t_start:.2f} seconds"
            )
        )
