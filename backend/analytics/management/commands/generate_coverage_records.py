import time

from django.core.management.base import BaseCommand
from django.db import connection

from analytics.models import Coverage
from analytics.tasks.coverage import test_coverage_for_dataset
from datasets.models import Dataset
from features.models import Feature


class Command(BaseCommand):
    help = "Generate missing coverage records and kick off spatial coverage checks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Also dispatch Celery tasks to check spatial coverage for unchecked records",
        )
        parser.add_argument(
            "--check-sync",
            action="store_true",
            help="Check spatial coverage synchronously instead of dispatching Celery tasks",
        )

    def handle(self, *args, **options):

        if not Feature.objects.exists():
            self.stdout.write("No features found in database")
            return

        if not Dataset.objects.exists():
            self.stdout.write("No datasets found in database")
            return

        # Generate missing coverage records
        num_records = self._gen_coverage_records()
        self.stdout.write(self.style.SUCCESS(f"Generated {num_records} missing coverage records"))

        # Optionally kick off coverage checks
        if options["check"] or options["check_sync"]:
            self._test_all_missing_coverage(options)


    def _gen_coverage_records(self):
        # Find all (feature, dataset) pairs that don't yet have a coverage record
        t_start = time.perf_counter()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id AS geom_id, d.id AS dataset_id
                FROM features f
                CROSS JOIN datasets d
                LEFT JOIN coverage c ON c.geom_id = f.id AND c.dataset_id = d.id
                WHERE c.geom_id IS NULL OR c.status = -1
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

        return len(records)


    def _test_all_missing_coverage(self, options):
        t_start = time.perf_counter()

        untested_dataset_ids = list(
            Coverage.objects.filter(status=-1)
            .values_list("dataset_id", flat=True)
            .distinct()
        )

        if not untested_dataset_ids:
            self.stdout.write("No untested coverage records to process")
            return

        for did in untested_dataset_ids:

            if options["check_sync"]:
                result = test_coverage_for_dataset(did)
                self.stdout.write(f"Dataset {did}: {result['covered']} covered, {result['not_covered']} not covered")
            else:
                test_coverage_for_dataset.delay(did)
                self.stdout.write(f"Dispatched coverage check for dataset {did}")

        elapsed = time.perf_counter() - t_start
        self.stdout.write(self.style.SUCCESS(f"Coverage checking completed/dispatched in {elapsed:.2f}s"))
