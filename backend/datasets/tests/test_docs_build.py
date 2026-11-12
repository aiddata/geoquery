import json
import tarfile
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from datasets.docs.build import build_bundle
from datasets.docs.grouping import GroupingError
from datasets.models import Dataset
from features.models import Feature, FeatMap, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin


@override_settings(FRONTEND_BASE_URL="https://app.example")
class BuildBundleTests(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        Dataset.objects.create(name="malaria", path="/malaria", type="raster", title="Malaria",
                               is_global=True, active=True, public=True)
        for level in (0, 1):
            fc = FeatureCollection.objects.create(
                name=f"gB_57dcd43_NPL_ADM{level}", path=f"/npl{level}", group_name="gb_v6_npl",
                group_level=level, group_title="Nepal - GeoBoundaries v6",
                source_name="geoBoundaries", active=True, public=True,
            )
            FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape="POINT(0 0)"))
        self.tmp = Path(tempfile.mkdtemp())
        self.bundle = self.tmp / "docs" / "data-docs.tar.gz"

    def test_bundle_contents_and_manifest(self):
        manifest = build_bundle(self.bundle)

        with tarfile.open(self.bundle) as tar:
            names = tar.getnames()
            self.assertEqual({n.split("/")[0] for n in names}, {"manifest.json", "datasets", "boundaries"})
            self.assertIn("datasets/malaria.md", names)
            self.assertIn("boundaries/gb-npl.md", names)
            stub = tar.extractfile("boundaries/gb-57dcd43-npl-adm1/index.html").read().decode()
            self.assertEqual(json.load(tar.extractfile("manifest.json")), manifest)
        self.assertIn("url=../gb-npl/#gb-57dcd43-npl-adm1", stub)
        self.assertEqual(
            {k: manifest[k] for k in ("datasets", "boundary_pages", "collections", "redirects")},
            {"datasets": 1, "boundary_pages": 1, "collections": 2, "redirects": 2},
        )
        self.assertEqual(list(self.bundle.parent.iterdir()), [self.bundle])

    def test_dataset_slug_collision_is_an_error(self):
        Dataset.objects.create(name="Malaria", path="/Malaria", type="raster", active=True, public=True)
        with self.assertRaises(GroupingError):
            build_bundle(self.bundle)

    def test_failed_build_leaves_no_partial_file(self):
        with mock.patch("datasets.docs.build.tarfile.open", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                build_bundle(self.bundle)
        self.assertEqual(list(self.bundle.parent.iterdir()), [])


class ScheduleTests(TestCase):
    def test_nightly_beat_entry_and_job_metrics(self):
        from analytics.background_metrics import JOBS

        entry = settings.CELERY_BEAT_SCHEDULE["build-data-docs"]
        self.assertEqual(entry["task"], "datasets.tasks.build_data_docs_task")
        self.assertEqual(entry["schedule"].hour, {5})
        self.assertIn("data_docs", JOBS)
