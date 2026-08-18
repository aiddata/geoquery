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
    help = "Ingest a generic boundary dataset from a boundary_ingest.json file"

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            help="Path to a boundary_ingest.json file",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip if a FeatureCollection with this name already exists",
        )
        parser.add_argument(
            "--reload-geometry",
            action="store_true",
            help="When updating an existing collection, wipe and re-ingest features. Without this flag, only metadata is updated.",
        )
        parser.add_argument(
            "--no-refresh-views",
            action="store_true",
            help="Skip refreshing materialized views after ingest (useful when ingesting many datasets in sequence)",
        )

    def handle(self, *args, **options):
        ingest_path = Path(options["path"])
        if not ingest_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {ingest_path}"))
            return

        ingest_dict = json.loads(ingest_path.read_text())

        self.stdout.write(f"Ingesting boundary from: {ingest_path}")
        self.ingest_boundary(
            ingest_dict,
            skip_existing=options["skip_existing"],
            reload_geometry=options["reload_geometry"],
        )

        if not options["no_refresh_views"]:
            self.stdout.write("Refreshing simplified-geometry materialized views...")
            refresh_materialized_views()
            self.stdout.write(self.style.SUCCESS("Materialized views refreshed."))

        self.stdout.write(self.style.SUCCESS("Done."))

    @transaction.atomic
    def ingest_boundary(self, ingest_dict: dict, skip_existing: bool, reload_geometry: bool):
        fc_name = ingest_dict.get("name")
        if not fc_name:
            raise ValueError("boundary_ingest.json must have a 'name' field")

        gpkg_path = Path(ingest_dict.get("path", ""))
        if not gpkg_path.exists():
            raise FileNotFoundError(f"Boundary file not found: {gpkg_path}")

        if skip_existing and FeatureCollection.objects.filter(name=fc_name).exists():
            self.stdout.write(self.style.WARNING(f"Skipping existing: {fc_name}"))
            return

        self.stdout.write(f"Processing: {fc_name}")

        try:
            gdf = gpd.read_file(gpkg_path)
        except Exception as e:
            logger.error(f"Failed to read {gpkg_path}: {e}")
            raise

        spatial_extent_wkt = shapely.box(*gdf.total_bounds).wkt

        defaults = {k: v for k, v in ingest_dict.items() if k != "name"}
        defaults["spatial_extent"] = GEOSGeometry(spatial_extent_wkt)

        fc, created = FeatureCollection.objects.update_or_create(
            name=fc_name,
            defaults=defaults,
        )

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} FeatureCollection: {fc_name}"))

        if not created and not reload_geometry:
            self.stdout.write("  Metadata updated, skipping geometry reload (use --reload-geometry to replace features)")
            return

        if not created:
            geom_ids = list(FeatMap.objects.filter(fc=fc).values_list("geom_id", flat=True))
            FeatMap.objects.filter(fc=fc).delete()
            Feature.objects.filter(id__in=geom_ids).delete()
            self.stdout.write(f"  Cleared existing features for {fc_name}")

        for _, row in gdf.iterrows():
            feature_geom = Feature.objects.create(shape=GEOSGeometry(row.geometry.wkt))
            FeatMap.objects.create(
                fc=fc,
                geom=feature_geom,
                name=row.get("shapeName"),
                attr=row.drop(["geometry"]).to_dict(),
                parent=None,
            )

        feature_count = FeatMap.objects.filter(fc=fc).count()
        self.stdout.write(self.style.SUCCESS(f"  Inserted {feature_count} features for {fc_name}"))
        logger.info(f"Successfully ingested {fc_name}")
