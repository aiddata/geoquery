import json
import os
import subprocess
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from datasets.ingest import ingest_dataset


class Command(BaseCommand):
    help = "Ingest a dataset from a JSON metadata file"

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            nargs="?",
            default=None,
            type=str,
            help="Path to the JSON metadata file for the dataset",
        )
        parser.add_argument(
            "--edit",
            action="store_true",
            help="Open $EDITOR to create the input JSON interactively",
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
        if options["edit"]:
            json_path = self._edit_tempfile(options["json_path"])
        elif options["json_path"]:
            json_path = Path(options["json_path"])
        else:
            raise CommandError("Provide a json_path or use --edit")

        if not json_path.exists():
            raise CommandError(f"JSON file not found: {json_path}")

        self.stdout.write(f"Ingesting dataset from {json_path}")

        ingest_dataset(
            json_data=json_path,
            update=options["update"],
            update_or_insert=options["update_or_insert"],
        )

        self.stdout.write(self.style.SUCCESS("Dataset ingest complete."))

    def _edit_tempfile(self, seed_path):
        editor = os.environ.get("EDITOR", "vi")

        initial = ""
        if seed_path:
            p = Path(seed_path)
            if p.exists():
                initial = p.read_text()

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tmp:
            tmp.write(initial)
            tmp_path = Path(tmp.name)

        try:
            subprocess.run([editor, str(tmp_path)], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            tmp_path.unlink(missing_ok=True)
            raise CommandError(f"Editor failed: {exc}")

        # Validate JSON before proceeding
        try:
            json.loads(tmp_path.read_text())
        except (json.JSONDecodeError, ValueError) as exc:
            tmp_path.unlink(missing_ok=True)
            raise CommandError(f"Invalid JSON: {exc}")

        return tmp_path
