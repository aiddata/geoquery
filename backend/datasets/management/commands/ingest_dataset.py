import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from datasets.ingest import ingest_dataset

GEO_DATASETS_REPO = "aiddata/geo-datasets"
GEO_DATASETS_BRANCH = "master"
GITHUB_API_BASE = f"https://api.github.com/repos/{GEO_DATASETS_REPO}/contents"
GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{GEO_DATASETS_REPO}/{GEO_DATASETS_BRANCH}"


class Command(BaseCommand):
    help = (
        "Ingest a dataset from a JSON metadata file, URL, or geo-datasets dataset name. "
        "When given a name (e.g. 'acled'), resolves all ingest JSONs from the "
        "aiddata/geo-datasets GitHub repo and ingests each one."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            nargs="?",
            default=None,
            type=str,
            help=(
                "Path or URL to a JSON metadata file, or a geo-datasets dataset "
                "directory name (e.g. 'acled'). Dataset names are resolved to raw "
                "GitHub URLs automatically."
            ),
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
            self._ingest_path(json_path, options)
            return

        src = options["json_path"]
        if not src:
            raise CommandError("Provide a json_path, URL, dataset name, or use --edit")

        if src.startswith("http://") or src.startswith("https://"):
            tmp = None
            try:
                json_path, tmp = self._download_url(src)
                self._ingest_path(json_path, options)
            finally:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
            return

        local = Path(src)
        if local.exists():
            self._ingest_path(local, options)
            return

        # Treat as a geo-datasets dataset directory name
        self._ingest_dataset_name(src, options)

    def _ingest_path(self, json_path: Path, options: dict):
        self.stdout.write(f"Ingesting dataset from {json_path}")
        ingest_dataset(
            json_data=json_path,
            update=options["update"],
            update_or_insert=options["update_or_insert"],
        )
        self.stdout.write(self.style.SUCCESS("Dataset ingest complete."))

    def _ingest_dataset_name(self, name: str, options: dict):
        self.stdout.write(f"Resolving ingest JSONs for dataset '{name}' from GitHub...")
        try:
            urls = self._resolve_dataset_urls(name)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise CommandError(
                    f"Dataset '{name}' not found in {GEO_DATASETS_REPO}/datasets/. "
                    "Check the directory name or pass a full URL/path."
                )
            raise CommandError(f"GitHub API error: {exc}")

        if not urls:
            raise CommandError(
                f"No ingest JSON files found for dataset '{name}' "
                f"(looked in datasets/{name}/ on branch {GEO_DATASETS_BRANCH})."
            )

        self.stdout.write(f"Found {len(urls)} ingest file(s):")
        for url in urls:
            self.stdout.write(f"  {url}")

        errors = []
        for url in urls:
            tmp = None
            try:
                json_path, tmp = self._download_url(url)
                self._ingest_path(json_path, options)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Failed {url}: {exc}"))
                errors.append((url, exc))
            finally:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)

        if errors:
            raise CommandError(f"{len(errors)} of {len(urls)} ingest(s) failed.")

    def _resolve_dataset_urls(self, dataset_name: str) -> list[str]:
        """Return raw GitHub download URLs for all ingest JSONs under datasets/<name>/."""
        def collect(api_path: str) -> list[str]:
            req = urllib.request.Request(
                f"{GITHUB_API_BASE}/{api_path}",
                headers={"Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req) as resp:
                items = json.loads(resp.read())

            urls = []
            for item in items:
                if (
                    item["type"] == "file"
                    and "ingest" in item["name"]
                    and item["name"].endswith(".json")
                ):
                    urls.append(item["download_url"])
                elif item["type"] == "dir":
                    urls.extend(collect(item["path"]))
            return urls

        return collect(f"datasets/{dataset_name}")

    def _download_url(self, url: str) -> tuple[Path, Path]:
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            urllib.request.urlretrieve(url, tmp_path)
            try:
                json.loads(tmp_path.read_text())
            except (json.JSONDecodeError, ValueError) as exc:
                tmp_path.unlink(missing_ok=True)
                raise CommandError(f"Downloaded content is not valid JSON: {exc}")
            return tmp_path, tmp_path
        except urllib.error.URLError as exc:
            raise CommandError(f"Failed to download {url}: {exc}")

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

        try:
            json.loads(tmp_path.read_text())
        except (json.JSONDecodeError, ValueError) as exc:
            tmp_path.unlink(missing_ok=True)
            raise CommandError(f"Invalid JSON: {exc}")

        return tmp_path
