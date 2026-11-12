"""Load public datasets and boundaries, write their docs pages, and bundle them.

build_bundle is what the nightly task runs. It writes the tarball the docs
workflow downloads, replacing the previous one atomically so a download never
sees a half-written file.
"""

import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Prefetch

from .coverage import page_coverage
from .grouping import GroupingError, build_pages
from .render import boundaries_index, boundary_page, dataset_page, datasets_index, redirect_html
from .text import slug

MEMBERS = ("datasets", "boundaries")


def load(using="replica"):
    from datasets.models import Dataset, DatasetResource
    from features.models import FeatMap, FeatureCollection

    datasets = list(
        Dataset.objects.using(using).filter(public=True, active=True)
        .prefetch_related(
            Prefetch("resources", queryset=DatasetResource.objects.using(using).order_by("temporal", "name")),
            "mappings",
        )
        .order_by("title", "name")
    )
    collections = list(
        FeatureCollection.objects.using(using).filter(public=True, active=True, is_user_upload=False)
    )
    feature_counts = dict(
        FeatMap.objects.using(using).filter(fc_id__in=[fc.id for fc in collections])
        .values("fc_id").annotate(n=Count("id")).values_list("fc_id", "n")
    )
    return datasets, collections, feature_counts


def write_pages(out_dir, datasets, collections, feature_counts, app_url, coverage=None) -> dict:
    """Replace out_dir/datasets and out_dir/boundaries with freshly generated
    pages, and return the manifest. Nothing else in out_dir is touched."""
    out_dir = Path(out_dir)
    pages = build_pages(collections)
    if coverage is None:
        coverage = page_coverage(pages, datasets)

    dataset_slugs = {}
    for ds in datasets:
        other = dataset_slugs.setdefault(slug(ds.name), ds.name)
        if other != ds.name:
            raise GroupingError(f"datasets {other!r} and {ds.name!r} would share datasets/{slug(ds.name)}/")

    for name in MEMBERS:
        shutil.rmtree(out_dir / name, ignore_errors=True)
        (out_dir / name).mkdir(parents=True)
    ds_dir, bd_dir = out_dir / "datasets", out_dir / "boundaries"

    for ds in datasets:
        available = [(p, coverage[p.slug][ds.id]) for p in pages if ds.id in coverage[p.slug]]
        (ds_dir / f"{slug(ds.name)}.md").write_text(dataset_page(ds, available), encoding="utf-8")
    (ds_dir / "index.md").write_text(datasets_index(datasets), encoding="utf-8")

    by_id = {ds.id: ds for ds in datasets}
    page_slugs = {p.slug for p in pages} | {"index"}
    redirects = 0
    for page in pages:
        covering = sorted(
            ((by_id[ds_id], status) for ds_id, status in coverage[page.slug].items()),
            key=lambda pair: (pair[0].title or pair[0].name).lower(),
        )
        (bd_dir / f"{page.slug}.md").write_text(
            boundary_page(page, covering, feature_counts, app_url), encoding="utf-8"
        )
        for fc in page.collections:
            old = slug(fc.name)
            if old in page_slugs:
                continue
            stub = bd_dir / old / "index.html"
            stub.parent.mkdir(exist_ok=True)
            stub.write_text(redirect_html(f"../{page.slug}/#{old}"), encoding="utf-8")
            redirects += 1
    (bd_dir / "index.md").write_text(boundaries_index(pages), encoding="utf-8")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": len(datasets),
        "boundary_pages": len(pages),
        "collections": len(collections),
        "redirects": redirects,
    }


def build_data_docs(out_dir) -> dict:
    datasets, collections, feature_counts = load()
    return write_pages(out_dir, datasets, collections, feature_counts, settings.FRONTEND_BASE_URL)


def build_bundle(bundle_path=None) -> dict:
    bundle_path = Path(bundle_path or settings.DATA_DOCS_BUNDLE)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pages_dir = Path(tmp) / "pages"
        manifest = build_data_docs(pages_dir)
        (pages_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        fd, partial = tempfile.mkstemp(prefix=".data-docs.", suffix=".tmp", dir=bundle_path.parent)
        try:
            with os.fdopen(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w:gz") as tar:
                for name in ("manifest.json", *MEMBERS):
                    tar.add(pages_dir / name, arcname=name)
            # mkstemp creates 0600; the backend pod serving the file needs to read it.
            os.chmod(partial, 0o664)
            os.replace(partial, bundle_path)
        except BaseException:
            Path(partial).unlink(missing_ok=True)
            raise
    return manifest
