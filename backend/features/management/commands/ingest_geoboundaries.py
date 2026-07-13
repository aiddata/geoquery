import concurrent.futures
import json
from pathlib import Path

import geopandas as gpd
import shapely
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand
from django.db import transaction
from loguru import logger

from features.matviews import refresh_materialized_views
from features.models import FeatMap, Feature, FeatureCollection


class Command(BaseCommand):
    help = "Ingest geoBoundaries data into the features database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--iso3",
            nargs="+",
            help="Specific ISO3 codes to download (e.g., GHA AFG)",
        )
        parser.add_argument(
            "--data-dir",
            type=str,
            default="/data/boundaries/geoboundaries/",
            help="Data dir for downloaded files",
        )
        parser.add_argument(
            "--commit",
            type=str,
            default="57dcd43",
            help="GitHub commit 7 char short hash for downloaded files (e.g., 57dcd43)",
        )
        parser.add_argument(
            "--active",
            action="store_true",
            help="Set feature collections as active",
        )
        parser.add_argument(
            "--public",
            action="store_true",
            help="Set feature collections as public",
        )
        parser.add_argument(
            "--concurrent",
            action="store_true",
            help="Run with concurrent processing",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip feature collections that already exist",
        )
        parser.add_argument(
            "--reload-geometry",
            action="store_true",
            help="When updating an existing collection, wipe and re-ingest features. Without this flag, only metadata is updated.",
        )

    def handle(self, *args, **options):
        self.iso3_list = options.get("iso3")
        self.set_active = options["active"]
        self.set_public = options["public"]
        self.run_concurrent = options["concurrent"]
        self.data_dir = Path(options["data_dir"])
        self.commit = options["commit"]
        self.data_path = self.data_dir / self.commit
        self.skip_existing = options["skip_existing"]
        self.reload_geometry = options["reload_geometry"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting geoBoundaries ingest with active={self.set_active}, public={self.set_public}"
            )
        )

        # Filter by ISO3 if specified, reference available ISO3 codes from the geoBoundaries data_path
        if self.iso3_list is None:
            ingest_items = [i.stem for i in self.data_path.rglob("*.gpkg") if (i.parent / f"raw_{i.stem}.json").exists()]
        else:
            ingest_items = [
                i.stem for i in self.data_path.rglob("*.gpkg") if i.stem.split("-")[1] in self.iso3_list and (i.parent / f"raw_{i.stem}.json").exists()
            ]

        ingest_items = sorted(ingest_items)

        if len(ingest_items) == 0:
            self.stdout.write(
                self.style.WARNING("No items found to process. Exiting.")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"Found {len(ingest_items)} items to process")
        )

        # Process items
        if self.run_concurrent:
            self.process_concurrent(ingest_items)
        else:
            self.process_sequential(ingest_items)

        # Refresh materialized views with simplified geometries
        self.stdout.write("Refreshing simplified-geometry materialized views...")
        refresh_materialized_views()
        self.stdout.write(self.style.SUCCESS("Materialized views refreshed."))

        self.stdout.write(self.style.SUCCESS("Finished geoBoundaries ingest"))

    def process_sequential(self, ingest_items):
        """Process items sequentially."""
        for item in ingest_items:
            try:
                self.ingest_gb_item(item)
            except Exception as e:
                logger.error(f"Error processing {item}: {e}")
                self.stderr.write(
                    self.style.ERROR(f"Error processing {item}: {e}")
                )

    def process_concurrent(self, ingest_items):
        """Process items concurrently."""
        with concurrent.futures.ProcessPoolExecutor() as executor:
            futures = [
                executor.submit(self.ingest_gb_item, item) for item in ingest_items
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

    @transaction.atomic
    def ingest_gb_item(self, fname):
        """Ingest a single geoBoundaries item."""
        item = json.loads((self.data_path / f"raw_{fname}.json").read_text())
        iso3 = item["boundaryISO"]
        boundary_type = item["boundaryType"]
        fc_name = f"gB_{self.commit}_{iso3}_{boundary_type}"

        # Check if already exists
        if (
            self.skip_existing
            and FeatureCollection.objects.filter(name=fc_name).exists()
        ):
            self.stdout.write(self.style.WARNING(f"Skipping existing: {fc_name}"))
            return

        self.stdout.write(f"Processing: {fc_name}")

        # Build metadata
        adm_meta = self.build_metadata(item, fc_name)

        # Process geodata
        item_stem = Path(item["gjDownloadURL"]).stem
        gpkg_path = self.data_path / f"{item_stem}.gpkg"
        adm_meta["path"] = str(gpkg_path)

        logger.debug(f"Reading {gpkg_path}")
        try:
            gdf = gpd.read_file(gpkg_path)
        except Exception as e:
            logger.error(f"Failed to read {gpkg_path}: {e}")
            self.stderr.write(
                self.style.ERROR(f"Failed to read {gpkg_path}: {e}")
            )
            return

        # Calculate spatial extent
        logger.debug(f"Calculating bounding box for {fc_name}")
        spatial_extent_wkt = shapely.box(*gdf.total_bounds).wkt

        # Create or update FeatureCollection
        fc, created = FeatureCollection.objects.update_or_create(
            name=fc_name,
            defaults={
                "active": self.set_active,
                "public": self.set_public,
                "path": str(gpkg_path),
                "file_extension": ".gpkg",
                "title": adm_meta["title"],
                "description": adm_meta["description"],
                "details": adm_meta.get("details", ""),
                "tags": adm_meta["tags"],
                "citation": adm_meta["citation"],
                "source_name": adm_meta["source_name"],
                "source_url": adm_meta["source_url"],
                "other": adm_meta["other"],
                "ingest_src": adm_meta["ingest_src"],
                "is_global": adm_meta["is_global"],
                "spatial_extent": GEOSGeometry(spatial_extent_wkt),
                "group_name": adm_meta["group_name"],
                "group_title": adm_meta["group_title"],
                "group_class": adm_meta["group_class"],
                "group_level": adm_meta["group_level"],
            },
        )

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} FeatureCollection: {fc_name}"))

        if not created and not self.reload_geometry:
            self.stdout.write(f"  Metadata updated, skipping geometry reload (use --reload-geometry to replace features)")
            return

        # Wipe existing features before reload
        if not created:
            geom_ids = list(FeatMap.objects.filter(fc=fc).values_list("geom_id", flat=True))
            FeatMap.objects.filter(fc=fc).delete()
            Feature.objects.filter(id__in=geom_ids).delete()
            self.stdout.write(f"  Cleared existing features for {fc_name}")

        # Insert features
        logger.debug(f"Inserting features for {fc_name}")
        for idx, row in gdf.iterrows():
            # Create Feature (geometry)
            feature_geom = Feature.objects.create(shape=GEOSGeometry(row.geometry.wkt))

            # Create FeatMap (links FC to Feature with attributes)
            FeatMap.objects.create(
                fc=fc,
                geom=feature_geom,
                name=row.get("shapeName"),
                attr=row.drop(["geometry"]).to_dict(),
                parent=None,
            )

        feature_count = FeatMap.objects.filter(fc=fc).count()
        self.stdout.write(
            self.style.SUCCESS(f"  Inserted {feature_count} features for {fc_name}")
        )

        # Export metadata to JSON
        export_meta = {k: v for k, v in adm_meta.items() if k != "features"}
        export_meta["spatial_extent"] = spatial_extent_wkt
        json_path = gpkg_path.with_suffix(".json")
        with open(json_path, "w") as file:
            json.dump(export_meta, file, indent=4)

        logger.info(f"Successfully ingested {fc_name}")

    def build_metadata(self, item: dict, fc_name: str) -> dict:
        """Build metadata dictionary for a geoBoundaries item."""
        iso3 = item["boundaryISO"]
        boundary_type = item["boundaryType"]

        raw_github_string_prefix = "https://github.com/wmgeolab/geoBoundaries/raw/"
        data_commit = item["gjDownloadURL"].replace(raw_github_string_prefix, "").split("/")[0]

        return {
            "active": self.set_active,
            "public": self.set_public,
            "name": fc_name,
            "path": None,  # Set later
            "file_extension": ".gpkg",
            "title": f"geoBoundaries v6 - {item['boundaryName']} {boundary_type}",
            "description": (
                f"This feature collection represents the {boundary_type} level "
                f"boundaries for {item['boundaryName']} ({iso3}) from geoBoundaries v6."
            ),
            "details": f"Based on GitHub commit {data_commit}",
            "tags": ["geoboundaries", "administrative", "boundary"],
            "citation": (
                "Runfola, D. et al. (2020) geoBoundaries: A global database of "
                "political administrative boundaries. PLoS ONE 15(4): e0231866. "
                "https://doi.org/10.1371/journal.pone.0231866"
            ),
            "source_name": "geoBoundaries",
            "source_url": "geoboundaries.org",
            "other": item.copy(),
            "ingest_src": "geoquery_automated",
            "is_global": False,
            "group_name": f"gb_v6_{iso3.lower()}",
            "group_title": f"{item['boundaryName']} - GeoBoundaries v6",
            "group_class": "parent" if boundary_type == "ADM0" else "child",
            "group_level": int(boundary_type[3:]),
        }
