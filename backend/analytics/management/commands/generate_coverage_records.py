
from django.core.management.base import BaseCommand

from analytics.tasks.coverage import create_missing_coverage_records, run_missing_coverage_checks
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
        result = create_missing_coverage_records()
        self.stdout.write(self.style.SUCCESS(f"Generated {result['created']} missing coverage records"))

        # Optionally kick off coverage checks
        if options["check"] or options["check_sync"]:
            run_missing_coverage_checks(sync=options["check_sync"])
