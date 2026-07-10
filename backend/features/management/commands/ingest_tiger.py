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
    help = "Ingest TIGER  data into the features database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            help="Path to the target ingest json",
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
            "--skip-existing",
            action="store_true",
            help="Skip feature collections that already exist",
        )

    def handle(self, *args, **options):
        self.path = options.get("path")
        self.set_active = options["active"]
        self.set_public = options["public"]
        self.skip_existing = options["skip_existing"]

        with open(self.path, "r") as file:
            self.ingest_dict = json.load(file)

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting TIGER ingest with active={self.set_active}, public={self.set_public}"
            )
        )

        # list current dir
        print("--------------------")
        print(list(Path("/data/TIGER").resolve().absolute().iterdir()))

        self.ingest_tiger_item()

        # Refresh materialized views with simplified geometries
        self.stdout.write("Refreshing simplified-geometry materialized views...")
        refresh_materialized_views()
        self.stdout.write(self.style.SUCCESS("Materialized views refreshed."))

        self.stdout.write(self.style.SUCCESS("Finished TIGER ingest"))

    @transaction.atomic
    def ingest_tiger_item(self):
        """Ingest TIGER item."""

        fc_name = self.ingest_dict["name"]

        # Check if already exists
        if (
            self.skip_existing
            and FeatureCollection.objects.filter(name=fc_name).exists()
        ):
            self.stdout.write(self.style.WARNING(f"Skipping existing: {fc_name}"))
            return

        self.stdout.write(f"Processing: {fc_name}")

        # Download and process geodata
        gpkg_path = Path(self.ingest_dict["path"])
        logger.debug(f"Reading {gpkg_path}")
        try:
            gdf = gpd.read_file(gpkg_path)
        except Exception as e:
            logger.error(f"Failed to read {gpkg_path}: {e}")
            self.stderr.write(
                self.style.ERROR(f"Failed to read {gpkg_path}: {e}")
            )
            raise

        # Calculate spatial extent
        logger.debug(f"Calculating bounding box for {gpkg_path}")
        spatial_extent_wkt = shapely.box(*gdf.total_bounds).wkt
        self.ingest_dict["spatial_extent"] = spatial_extent_wkt
        # Create or update FeatureCollection
        fc, created = FeatureCollection.objects.update_or_create(
            name=fc_name,
            defaults=self.ingest_dict,
        )

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} FeatureCollection: {fc_name}"))

        # Delete existing features if updating
        if not created:
            FeatMap.objects.filter(fc=fc).delete()
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

        logger.info(f"Successfully ingested {fc_name}")
