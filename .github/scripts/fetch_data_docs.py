"""Download the generated data docs pages into docs/data_documentation.

The pages are generated nightly in the cluster (datasets.tasks.build_data_docs_task
in the backend), which writes a bundle into the requests share. The app serves it
at <app_url>/requests/docs/data-docs.tar.gz, with app_url read from zensical.toml.

Exits 1 when the bundle is missing, unreadable or much smaller than expected,
before touching anything, so a bad night never replaces the live docs. Warns
when the bundle is stale, which means the nightly task has stopped.

Usage: python3 .github/scripts/fetch_data_docs.py [bundle-url]
"""

import http.client
import io
import json
import shutil
import sys
import tarfile
import time
import tomllib
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "docs" / "data_documentation"
MEMBERS = ("datasets", "boundaries")
MIN_DATASETS = 40
MIN_BOUNDARY_PAGES = 200
STALE_AFTER = timedelta(days=3)


class BundleError(Exception):
    pass


def bundle_url(config=REPO / "zensical.toml") -> str:
    with open(config, "rb") as fh:
        app_url = tomllib.load(fh)["project"]["extra"]["app_url"]
    return app_url.rstrip("/") + "/requests/docs/data-docs.tar.gz"


def download(url: str) -> bytes:
    # Cloudflare caches the bundle by URL; a query string it hasn't seen makes
    # it fetch the current file from the app instead of serving yesterday's.
    fresh = f"{url}{'&' if '?' in url else '?'}v={int(time.time())}"
    request = urllib.request.Request(fresh, headers={"User-Agent": "geoquery-docs-build"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except (OSError, http.client.HTTPException) as exc:
        raise BundleError(f"could not download {url}: {exc}") from exc


def check_manifest(manifest: dict, now=None) -> list:
    """Raise BundleError if the bundle is too small or malformed; return any warnings."""
    try:
        datasets, pages = manifest.get("datasets", 0), manifest.get("boundary_pages", 0)
        if datasets < MIN_DATASETS or pages < MIN_BOUNDARY_PAGES:
            raise BundleError(
                f"bundle has {datasets} datasets and {pages} boundary pages; "
                f"expected at least {MIN_DATASETS} and {MIN_BOUNDARY_PAGES}"
            )
        generated = datetime.fromisoformat(manifest["generated_at"])
        age = (now or datetime.now(timezone.utc)) - generated
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise BundleError(f"manifest.json is malformed ({type(exc).__name__}: {exc}); "
                          "expected generated_at (timezone-aware ISO timestamp) and integer counts") from exc
    if age > STALE_AFTER:
        return [f"bundle was generated {age.days} days ago ({manifest['generated_at']}); "
                "is build_data_docs_task running?"]
    return []


def unpack(data: bytes, target: Path):
    try:
        # "r:*" because Cloudflare serves the .tar.gz decompressed: a plain tar
        # with no Content-Encoding header.
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError as exc:
        raise BundleError(f"not a tar archive (gzip or plain): {exc}") from exc
    with tar:
        try:
            manifest = json.load(tar.extractfile("manifest.json"))
        except (KeyError, TypeError, ValueError) as exc:
            raise BundleError(f"bundle has no valid manifest.json: {exc}") from exc
        except (EOFError, zlib.error, tarfile.TarError) as exc:
            raise BundleError(f"bundle is truncated or corrupt: {exc}") from exc
        warnings = check_manifest(manifest)
        try:
            members = [m for m in tar.getmembers() if m.name.split("/")[0] in MEMBERS]
            for member in members:
                tarfile.data_filter(member, str(target))
        except tarfile.FilterError as exc:
            raise BundleError(f"bundle contains an unsafe member: {exc}") from exc
        except (EOFError, zlib.error, tarfile.TarError) as exc:
            raise BundleError(f"bundle is truncated or corrupt: {exc}") from exc
        for name in MEMBERS:
            shutil.rmtree(target / name, ignore_errors=True)
        try:
            tar.extractall(target, members=members, filter="data")
        except (EOFError, zlib.error, tarfile.TarError) as exc:
            raise BundleError(f"bundle is truncated or corrupt: {exc}") from exc
    return manifest, warnings


def main(argv) -> int:
    url = argv[1] if len(argv) > 1 else bundle_url()
    try:
        manifest, warnings = unpack(download(url), TARGET)
    except BundleError as exc:
        print(f"::error::{exc}")
        return 1
    for warning in warnings:
        print(f"::warning::{warning}")
    print(f"Unpacked {manifest['datasets']} dataset pages and {manifest['boundary_pages']} "
          f"boundary pages generated {manifest['generated_at']} from {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
