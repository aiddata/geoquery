import contextlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_data_docs as f  # noqa: E402


def bundle(manifest=None, extra=()):
    manifest = manifest or {"generated_at": datetime.now(timezone.utc).isoformat(),
                            "datasets": 63, "boundary_pages": 235}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        files = {"manifest.json": json.dumps(manifest), "datasets/index.md": "# Datasets\n",
                 "boundaries/gb-npl.md": "# Nepal boundaries\n", **dict(extra)}
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class UnpackTests(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp())
        (self.target / "datasets").mkdir()
        (self.target / "datasets" / "old.md").write_text("old")
        (self.target / "index.md").write_text("hand-written")

    def test_replaces_only_the_generated_directories(self):
        manifest, warnings = f.unpack(bundle(extra={"evil.md": "x"}), self.target)
        self.assertEqual(manifest["datasets"], 63)
        self.assertEqual(warnings, [])
        self.assertTrue((self.target / "boundaries" / "gb-npl.md").exists())
        self.assertFalse((self.target / "datasets" / "old.md").exists())
        self.assertFalse((self.target / "evil.md").exists())
        self.assertEqual((self.target / "index.md").read_text(), "hand-written")

    def test_too_small_bundle_fails_and_touches_nothing(self):
        small = {"generated_at": datetime.now(timezone.utc).isoformat(), "datasets": 3, "boundary_pages": 235}
        with self.assertRaisesRegex(f.BundleError, "3 datasets"):
            f.unpack(bundle(small), self.target)
        self.assertTrue((self.target / "datasets" / "old.md").exists())

    def test_not_a_tarball(self):
        with self.assertRaisesRegex(f.BundleError, "gzip"):
            f.unpack(b"<html>404</html>", self.target)

    def test_missing_manifest(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz"):
            pass
        with self.assertRaisesRegex(f.BundleError, "manifest"):
            f.unpack(buf.getvalue(), self.target)

    def test_stale_bundle_warns(self):
        old = {"generated_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
               "datasets": 63, "boundary_pages": 235}
        _, warnings = f.unpack(bundle(old), self.target)
        self.assertEqual(len(warnings), 1)
        self.assertIn("5 days ago", warnings[0])


    def assert_rejected_untouched(self, data):
        with self.assertRaises(f.BundleError):
            f.unpack(data, self.target)
        self.assertTrue((self.target / "datasets" / "old.md").exists())

    def test_symlink_member_pointing_outside_is_rejected(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(bundle()), mode="r:gz") as src, \
                tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for m in src.getmembers():
                tar.addfile(m, src.extractfile(m) if m.isfile() else None)
            link = tarfile.TarInfo("datasets/evil")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tar.addfile(link)
        self.assert_rejected_untouched(buf.getvalue())

    def test_path_traversal_member_is_rejected(self):
        self.assert_rejected_untouched(bundle(extra={"datasets/../../escape.md": "x"}))
        self.assertFalse((self.target.parent / "escape.md").exists())

    def test_truncated_bundle_is_rejected(self):
        data = bundle()
        self.assert_rejected_untouched(data[: len(data) // 2])

    def test_manifest_without_generated_at_is_rejected(self):
        self.assert_rejected_untouched(bundle({"datasets": 63, "boundary_pages": 235}))

    def test_bad_manifest_values_are_rejected(self):
        for manifest in (
            {"generated_at": "2026-01-01T00:00:00", "datasets": 63, "boundary_pages": 235},
            {"generated_at": "nonsense", "datasets": 63, "boundary_pages": 235},
            {"generated_at": datetime.now(timezone.utc).isoformat(), "datasets": "63", "boundary_pages": 235},
        ):
            with self.subTest(manifest=manifest):
                self.assert_rejected_untouched(bundle(manifest))


class MainTests(unittest.TestCase):
    def test_bundle_error_prints_annotation_and_returns_1(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(f, "TARGET", Path(tmp)), \
                mock.patch.object(f, "download", side_effect=f.BundleError("boom")), \
                contextlib.redirect_stdout(out):
            self.assertEqual(f.main(["fetch_data_docs.py", "https://app.example/x"]), 1)
        self.assertTrue(out.getvalue().startswith("::error::"))


class ServedFormTests(unittest.TestCase):
    """Cloudflare serves the .tar.gz decompressed (plain tar, no Content-Encoding)
    and caches it, so the script must accept both forms and bypass the cache."""

    def test_plain_tar_is_accepted(self):
        import gzip
        target = Path(tempfile.mkdtemp())
        manifest, _ = f.unpack(gzip.decompress(bundle()), target)
        self.assertEqual(manifest["datasets"], 63)
        self.assertTrue((target / "boundaries" / "gb-npl.md").exists())

    def test_download_bypasses_the_cache(self):
        from unittest import mock
        seen = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout):
            seen.append(request.full_url)
            return Response(b"data")

        with mock.patch.object(f.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(f.download("https://app.example/requests/docs/data-docs.tar.gz"), b"data")
        self.assertRegex(seen[0], r"^https://app\.example/requests/docs/data-docs\.tar\.gz\?v=\d+$")


class BundleUrlTests(unittest.TestCase):
    def test_url_comes_from_app_url(self):
        config = Path(tempfile.mkdtemp()) / "zensical.toml"
        config.write_text('[project.extra]\napp_url = "https://app.example/"\n')
        self.assertEqual(f.bundle_url(config), "https://app.example/requests/docs/data-docs.tar.gz")


if __name__ == "__main__":
    unittest.main()
