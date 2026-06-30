import concurrent.futures
import json
from pathlib import Path

import geopandas as gpd
import requests
from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = "Download geoBoundaries data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            type=str,
            default="0faed0c",
            help="Target geoBoundaries commit hash",
        )
        parser.add_argument(
            "--iso3",
            nargs="+",
            help="Specific ISO3 codes to download (e.g., GHA AFG)",
        )
        parser.add_argument(
            "--concurrent",
            action="store_true",
            help="Run with concurrent processing",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="/geo-datasets/data/boundaries/geoboundaries/",
            help="Output dir for downloaded files",
        )
        parser.add_argument(
            "--output-label",
            type=str,
            default="gBv6_9469f09_57dcd43",
            help="Output label for downloaded files",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip feature collections that already exist",
        )

    def handle(self, *args, **options):
        self.target_gb_commit = options["commit"]
        self.dl_iso3_list = options.get("iso3")
        self.run_concurrent = options["concurrent"]
        self.output_dir = Path(options["output_dir"])
        self.output_label = options["output_label"]
        self.output_tag = self.output_label.split("_")[0]
        self.output_path = self.output_dir / self.output_label
        self.skip_existing = options["skip_existing"]

        # Create output directory
        self.output_path.mkdir(exist_ok=True, parents=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting geoBoundaries download"
            )
        )

        # Fetch API data
        all_url = f"https://raw.githubusercontent.com/wmgeolab/gbWeb/{self.target_gb_commit}/api/current/gbOpen/ALL/ALL/index.json"

        self.stdout.write(f"Fetching geoBoundaries metadata from {all_url}")
        api_data = self.get_api_url(all_url)

        # Filter by ISO3 if specified
        if self.dl_iso3_list is None:
            dl_items = api_data
        else:
            dl_items = [
                i for i in api_data if i["boundaryISO"] in self.dl_iso3_list
            ]

        dl_items = sorted(dl_items, key=lambda d: d["boundaryISO"])

        self.stdout.write(
            self.style.SUCCESS(f"Found {len(dl_items)} items to download")
        )

        # Process items
        if self.run_concurrent:
            self.process_concurrent(dl_items)
        else:
            self.process_sequential(dl_items)

        self.stdout.write(self.style.SUCCESS("Finished geoBoundaries download"))

    def get_api_url(self, url):
        """Fetch JSON data from a URL."""
        response = requests.get(url)
        response.raise_for_status()
        return response.json()

    def process_sequential(self, dl_items):
        """Process items sequentially."""
        for item in dl_items:
            try:
                self.dl_gb_item(item)
            except Exception as e:
                logger.error(f"Error processing {item.get('boundaryISO')}: {e}")
                self.stderr.write(
                    self.style.ERROR(f"Error processing {item.get('boundaryISO')}: {e}")
                )

    def process_concurrent(self, dl_items):
        """Process items concurrently."""
        with concurrent.futures.ProcessPoolExecutor() as executor:
            futures = [
                executor.submit(self.dl_gb_item, item) for item in dl_items
            ]

            errors = []
            for result in concurrent.futures.as_completed(futures):
                if result.exception() is not None:
                    errors.append(result.exception())

            if len(errors) > 0:
                unique_errors = set([str(x) for x in errors])
                self.stderr.write(
                    self.style.ERROR(
                        f"{len(errors)} exceptions occurred ({len(unique_errors)} unique)"
                    )
                )
                for err in unique_errors:
                    self.stderr.write(self.style.ERROR(f"  - {err}"))

    def dl_gb_item(self, item: dict):
        """Download a single geoBoundaries item."""
        iso3 = item["boundaryISO"]
        fc_type = item["boundaryType"]
        fc_name = f"{self.output_tag}_{iso3}_{fc_type}"

        self.stdout.write(f"Processing: {fc_name}")

        # Download and process geodata
        commit_dl_url = item["gjDownloadURL"]
        gpkg_path = self.output_path / f"{Path(commit_dl_url).stem}.gpkg"
        raw_meta_path = self.output_path / f"raw_{Path(commit_dl_url).stem}.json"

        # Check if already exists
        if self.skip_existing and gpkg_path.exists() and raw_meta_path.exists():
            self.stdout.write(self.style.WARNING(f"Skipping existing: {fc_name}"))
            return

        logger.debug(f"Downloading {commit_dl_url}")
        try:
            gdf = gpd.read_file(commit_dl_url)
        except Exception:
            if requests.get(commit_dl_url).status_code == 404:
                logger.error(f"404: {commit_dl_url}")
                self.stderr.write(self.style.ERROR(f"404 Not Found: {commit_dl_url}"))
                return
            else:
                try:
                    raw_json = self.get_api_url(commit_dl_url)
                    gdf = gpd.GeoDataFrame.from_features(raw_json["features"])
                except Exception as e2:
                    logger.error(f"Failed to download {commit_dl_url}: {e2}")
                    self.stderr.write(
                        self.style.ERROR(f"Failed to download {commit_dl_url}: {e2}")
                    )
                    return

        # Ensure shapeName column exists
        if "shapeName" not in gdf.columns:
            potential_name_field = f"{fc_type}_NAME"
            if potential_name_field in gdf.columns:
                gdf["shapeName"] = gdf[potential_name_field]
            else:
                gdf["shapeName"] = None

        # Save to file
        gdf.to_file(gpkg_path, driver="GPKG")

        # Export raw gB metadata to JSON
        with open(raw_meta_path, "w") as file:
            json.dump(item, file, indent=4)

        logger.info(f"Successfully downloaded {fc_name}")
