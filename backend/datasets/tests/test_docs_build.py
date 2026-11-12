import json
import os
import shutil
import stat
import time
import tarfile
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from datasets.docs.build import build_bundle, load, write_pages
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
        self.addCleanup(shutil.rmtree, self.tmp, True)

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

    def test_dataset_slugged_index_is_an_error(self):
        Dataset.objects.create(name="Index", path="/Index", type="raster", active=True, public=True)
        with self.assertRaisesRegex(GroupingError, "index"):
            build_bundle(self.bundle)

    def test_failed_build_leaves_no_partial_file(self):
        with mock.patch("datasets.docs.build.tarfile.open", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                build_bundle(self.bundle)
        self.assertEqual(list(self.bundle.parent.iterdir()), [])

    def test_existing_bundle_survives_a_failed_build(self):
        self.bundle.parent.mkdir(parents=True)
        self.bundle.write_bytes(b"previous bundle")
        with mock.patch("datasets.docs.build.tarfile.TarFile.add", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                build_bundle(self.bundle)
        self.assertEqual(self.bundle.read_bytes(), b"previous bundle")
        self.assertEqual(list(self.bundle.parent.iterdir()), [self.bundle])

    def test_write_pages_preserves_other_files_and_drops_stale_pages(self):
        out = self.tmp / "out"
        (out / "boundaries").mkdir(parents=True)
        (out / "index.md").write_text("keep")
        (out / "boundaries" / "old.md").write_text("stale")
        write_pages(out, *load(), "https://app.example")
        self.assertEqual((out / "index.md").read_text(), "keep")
        self.assertFalse((out / "boundaries" / "old.md").exists())
        self.assertTrue((out / "boundaries" / "gb-npl.md").exists())

    def test_bundle_file_mode(self):
        build_bundle(self.bundle)
        self.assertEqual(stat.S_IMODE(self.bundle.stat().st_mode), 0o664)

    def test_collection_named_like_its_page_gets_no_stub(self):
        FeatureCollection.objects.create(
            name="gb-npl", path="/npl-x", group_name="gb_v6_npl", group_level=2,
            group_title="Nepal - GeoBoundaries v6", source_name="geoBoundaries", active=True, public=True,
        )
        manifest = build_bundle(self.bundle)
        with tarfile.open(self.bundle) as tar:
            names = tar.getnames()
        self.assertNotIn("boundaries/gb-npl/index.html", names)
        self.assertEqual(manifest["collections"], 3)
        self.assertEqual(manifest["redirects"], 2)

    def test_stale_temp_files_are_removed_but_fresh_ones_kept(self):
        self.bundle.parent.mkdir(parents=True)
        old = self.bundle.parent / ".data-docs.x.tmp"
        fresh = self.bundle.parent / ".data-docs.y.tmp"
        old.write_bytes(b"x")
        fresh.write_bytes(b"y")
        two_hours_ago = time.time() - 7200
        os.utime(old, (two_hours_ago, two_hours_ago))
        build_bundle(self.bundle)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())


class ScheduleTests(TestCase):
    def test_nightly_beat_entry_and_job_metrics(self):
        from analytics.background_metrics import JOBS

        entry = settings.CELERY_BEAT_SCHEDULE["build-data-docs"]
        self.assertEqual(entry["task"], "datasets.tasks.build_data_docs_task")
        self.assertEqual(entry["schedule"].hour, {5})
        self.assertIn("data_docs", JOBS)
