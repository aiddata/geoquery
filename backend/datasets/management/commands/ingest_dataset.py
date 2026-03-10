from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from datasets.ingest import ingest_dataset


class Command(BaseCommand):
    help = "Ingest a dataset from a JSON metadata file"

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            type=str,
            help="Path to the JSON metadata file for the dataset",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update an existing dataset (errors if it doesn't exist)",
        )
        parser.add_argument(
            "--update-or-insert",
            action="store_true",
            help="Try to update the dataset, inserting it if it doesn't exist",
        )

    def handle(self, *args, **options):
        json_path = Path(options["json_path"])

        if not json_path.exists():
            raise CommandError(f"JSON file not found: {json_path}")

        self.stdout.write(f"Ingesting dataset from {json_path}")

        ingest_dataset(
            json_data=json_path,
            update=options["update"],
            update_or_insert=options["update_or_insert"],
        )

        self.stdout.write(self.style.SUCCESS("Dataset ingest complete."))
