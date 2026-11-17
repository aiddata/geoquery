"""Copy processing option descriptions from geo-datasets ingest JSONs.

Only ProcessingOption.description changes, through a bulk UPDATE: no save
signals fire, and the processing_options trigger records changes to
dataset_id and active only, so no extract task, coverage or sync work is
triggered. Nothing is created or deleted, and nothing else is updated.

    uv run manage.py update_measure_descriptions --dry-run
    uv run manage.py update_measure_descriptions
    uv run manage.py update_measure_descriptions --source /path/to/geo-datasets
"""

import io
import json
import tarfile
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.models import ProcessingOption
from datasets.models import Dataset

GEO_DATASETS_TARBALL = "https://codeload.github.com/aiddata/geo-datasets/tar.gz/refs/heads/master"


def _ingest_docs(source: str):
    """Yield (path, parsed JSON) for every JSON file in the source.

    The source is a JSON file, a directory (searched recursively), or a URL
    to a .tar.gz of a geo-datasets checkout (the default: master, fetched in
    one request rather than through the rate-limited GitHub API).
    """
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": "geoquery-update-measures"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.endswith(".json"):
                    try:
                        yield member.name, json.load(tar.extractfile(member))
                    except ValueError:
                        continue
        return
    path = Path(source)
    if not path.exists():
        raise CommandError(f"Source not found: {source}")
    for p in [path] if path.is_file() else sorted(path.rglob("*.json")):
        try:
            yield str(p), json.loads(p.read_text())
        except ValueError:
            continue


def plan_updates(docs) -> tuple[list[tuple[int, str, str, str, str]], list[str]]:
    """Description changes to make: [(po id, dataset, short_name, old, new)].

    Only options that already exist (matched by dataset name and short_name)
    and whose description differs are included. Also returns notes on
    datasets the database doesn't have.
    """
    changes, notes = [], []
    seen = set()
    for path, doc in docs:
        if not isinstance(doc, dict) or not doc.get("name") or not doc.get("processing_options"):
            continue
        name = doc["name"]
        if name in seen:
            notes.append(f"{name}: defined again in {path}, skipped")
            continue
        seen.add(name)
        wanted = {
            po["short_name"]: po["description"]
            for po in doc["processing_options"]
            if isinstance(po, dict) and po.get("short_name") and isinstance(po.get("description"), str)
        }
        if not wanted:
            continue
        options = ProcessingOption.objects.filter(dataset__name=name, short_name__in=wanted)
        if not Dataset.objects.filter(name=name).exists():
            notes.append(f"{name}: not in this database, skipped")
            continue
        for po_id, short_name, old in options.values_list("id", "short_name", "description"):
            new = wanted[short_name]
            if (old or "") != new:
                changes.append((po_id, name, short_name, old or "", new))
    return changes, notes


class Command(BaseCommand):
    help = (
        "Update processing option descriptions from geo-datasets ingest JSONs. "
        "Changes descriptions only; triggers no ingest or extract work."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=GEO_DATASETS_TARBALL,
            help="Ingest JSON file, directory, or .tar.gz URL (default: geo-datasets master).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Show the changes without applying them.")

    def handle(self, *args, **options):
        changes, notes = plan_updates(_ingest_docs(options["source"]))
        for note in notes:
            self.stdout.write(f"  note: {note}")
        for _, name, short_name, old, new in changes:
            self.stdout.write(f"  {name} / {short_name}\n    was: {old}\n    now: {new}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"Dry run: {len(changes)} description(s) would change."))
            return
        with transaction.atomic():
            for po_id, *_rest, new in changes:
                ProcessingOption.objects.filter(id=po_id).update(description=new)
        self.stdout.write(self.style.SUCCESS(f"Updated {len(changes)} description(s)."))
