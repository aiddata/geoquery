import json
import tempfile
import urllib.request
from pathlib import Path

import geopandas as gpd
import shapely
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import CommandError

from analytics.management.commands.base import BaseIngestCommand
from django.db import transaction
from loguru import logger

from features.matviews import update_simplified_geometries
from features.models import FeatMap, Feature, FeatureCollection


def _to_json_safe(d: dict) -> dict:
    import math
    result = {}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            result[k] = None
        else:
            result[k] = v
    return result


class Command(BaseIngestCommand):
    help = "Ingest a generic boundary dataset from a boundary_ingest.json file or URL"

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            help="Path or URL to a boundary_ingest.json file",
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
            help="Skip updating the simplified-geometry tables during ingest (run `manage.py rebuild_simplified_geometries` afterwards)",
        )

    def handle(self, *args, **options):
        src = options["path"]
        tmp_path = None

        try:
            if src.startswith("http://") or src.startswith("https://"):
                ingest_path, tmp_path = self._download_url(src)
            else:
                ingest_path = Path(src)
                if not ingest_path.exists():
                    raise CommandError(f"File not found: {ingest_path}")

            ingest_dict = json.loads(ingest_path.read_text())

            self.stdout.write(f"Ingesting boundary from: {src}")
            self.ingest_boundary(
                ingest_dict,
                skip_existing=options["skip_existing"],
                reload_geometry=options["reload_geometry"],
                refresh_views=not options["no_refresh_views"],
            )
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

        self.stdout.write(self.style.SUCCESS("Done."))

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

    @transaction.atomic
    def ingest_boundary(self, ingest_dict: dict, skip_existing: bool, reload_geometry: bool, refresh_views: bool = True):
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
                attr=_to_json_safe(row.drop(["geometry"]).to_dict()),
                parent=None,
            )

        feature_count = FeatMap.objects.filter(fc=fc).count()
        self.stdout.write(self.style.SUCCESS(f"  Inserted {feature_count} features for {fc_name}"))

        # Inside the atomic block, so the simplified rows commit with the
        # features they were derived from.
        if refresh_views:
            update_simplified_geometries(fc.id)
            self.stdout.write(f"  Updated simplified geometries for {fc_name}")

        logger.info(f"Successfully ingested {fc_name}")
