import time

from django.core.management.base import BaseCommand
from django.db import connection

from analytics.models import Coverage
from analytics.tasks.coverage import test_coverage_for_dataset
from datasets.models import Dataset
from features.models import Feature


class Command(BaseCommand):
    help = "Generate missing coverage records and kick off spatial coverage testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--test",
            action="store_true",
            help="Also dispatch Celery tasks to test spatial coverage for untested records",
        )
        parser.add_argument(
            "--test-sync",
            action="store_true",
            help="Test spatial coverage synchronously instead of dispatching Celery tasks",
        )

    def handle(self, *args, **options):
        if not Feature.objects.exists():
            self.stdout.write("No features found in database")
            return

        dataset_ids = list(
            Dataset.objects.filter(coverage_dependency__isnull=True)
            .values_list("id", flat=True)
        )
        if not dataset_ids:
            self.stdout.write("No datasets without coverage dependencies found")
            return

        # Find all (feature, dataset) pairs that don't yet have a coverage record
        t_start = time.perf_counter()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id AS geom_id, d.id AS dataset_id
                FROM features f
                CROSS JOIN datasets d
                LEFT JOIN coverage c ON c.geom_id = f.id AND c.dataset_id = d.id
                WHERE d.coverage_dependency_id IS NULL
                  AND (c.geom_id IS NULL
                    OR c.status = -1)
                """
            )
            missing_pairs = cursor.fetchall()

        if not missing_pairs:
            self.stdout.write(self.style.SUCCESS("No missing coverage records"))
        else:
            records = [
                Coverage(geom_id=geom_id, dataset_id=dataset_id, status=-1)
                for geom_id, dataset_id in missing_pairs
            ]
            Coverage.objects.bulk_create(records, ignore_conflicts=True)

            elapsed = time.perf_counter() - t_start
            self.stdout.write(
                self.style.SUCCESS(
                    f"Inserted {len(records)} coverage records in {elapsed:.2f}s"
                )
            )

        # Optionally kick off coverage testing
        if options["test"] or options["test_sync"]:
            untested_dataset_ids = list(
                Coverage.objects.filter(status=-1)
                .values_list("dataset_id", flat=True)
                .distinct()
            )

            if not untested_dataset_ids:
                self.stdout.write("No untested coverage records to process")
                return

            if options["test_sync"]:
                self.stdout.write(
                    f"Testing coverage synchronously for {len(untested_dataset_ids)} datasets..."
                )
                t_start = time.perf_counter()
                for did in untested_dataset_ids:
                    result = test_coverage_for_dataset(did)
                    self.stdout.write(
                        f"  Dataset {did}: {result['covered']} covered, "
                        f"{result['not_covered']} not covered"
                    )
                elapsed = time.perf_counter() - t_start
                self.stdout.write(
                    self.style.SUCCESS(f"Coverage testing complete in {elapsed:.2f}s")
                )
            else:
                for did in untested_dataset_ids:
                    test_coverage_for_dataset.delay(did)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Dispatched {len(untested_dataset_ids)} coverage test tasks to Celery"
                    )
                )
