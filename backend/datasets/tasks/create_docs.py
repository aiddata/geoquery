import logging
import re
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _absolute_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def _optional_row(label: str, value) -> str:
    if value is None or value == "" or value == []:
        return ""
    return f"| {label} | {value} |\n"


def _build_dataset_page(dataset) -> str:
    resources = list(dataset.resources.order_by("temporal", "name"))
    mappings = list(dataset.mappings.order_by("map_val"))

    lines = []

    lines.append(f"# {dataset.title or dataset.name}\n")

    if dataset.description:
        lines.append(f"{dataset.description}\n")

    if dataset.details:
        lines.append(f"{dataset.details}\n")

    # Core details table
    lines.append("## Details\n")
    lines.append("| | |\n|---|---|\n")
    lines.append(_optional_row("Type", dataset.type))
    lines.append(_optional_row("Global coverage", "Yes" if dataset.is_global else None))

    if dataset.temporal_start or dataset.temporal_end:
        start = dataset.temporal_start.strftime("%Y-%m-%d") if dataset.temporal_start else "—"
        end = dataset.temporal_end.strftime("%Y-%m-%d") if dataset.temporal_end else "—"
        label = dataset.temporal_name or "Temporal range"
        lines.append(f"| {label} | {start} – {end} |\n")

    lines.append(_optional_row("Temporal type", dataset.temporal_type))
    lines.append(_optional_row("Tags", ", ".join(dataset.tags) if dataset.tags else None))
    if dataset.variable_description:
        desc = dataset.variable_description
        if dataset.variable_factor and dataset.variable_factor != 1.0:
            desc += f" (factor: {dataset.variable_factor})"
        lines.append(f"| Variable | {desc} |\n")
    if dataset.source_name:
        url = _absolute_url(dataset.source_url or "")
        if url:
            lines.append(f"| Source | [{dataset.source_name}]({url}) |\n")
        else:
            lines.append(f"| Source | {dataset.source_name} |\n")

    # Resources
    if resources:
        lines.append("\n## Resources\n")
        lines.append("| Name | Label | Date |\n|---|---|---|\n")
        for r in resources:
            date = r.temporal.strftime("%Y-%m-%d") if r.temporal else "—"
            label = r.label or "—"
            lines.append(f"| {r.name} | {label} | {date} |\n")

    # Value mappings
    if mappings:
        lines.append("\n## Value Mappings\n")
        lines.append("| Value | Label |\n|---|---|\n")
        for m in mappings:
            lines.append(f"| {m.map_val} | {m.map_name or '—'} |\n")

    # Citation
    if dataset.citation:
        lines.append("\n## Citation\n")
        lines.append(f"{dataset.citation}\n")

    return "".join(lines)


def _build_dataset_index(datasets) -> str:
    lines = ["# Datasets\n\n"]
    lines.append(
        "This page lists all datasets available in GeoQuery. "
        "Click a dataset name for full details.\n\n"
    )
    lines.append("| Dataset | Type | Temporal Range | Description |\n")
    lines.append("|---|---|---|---|\n")

    for ds in datasets:
        slug = _slug(ds.name)
        name_link = f"[{ds.title or ds.name}]({slug}.md)"
        temporal = "—"
        if ds.temporal_start or ds.temporal_end:
            start = ds.temporal_start.strftime("%Y") if ds.temporal_start else "—"
            end = ds.temporal_end.strftime("%Y") if ds.temporal_end else "—"
            temporal = f"{start}–{end}"
        description = (ds.description or "").replace("|", "\\|")[:120]
        if len(ds.description or "") > 120:
            description += "…"
        lines.append(f"| {name_link} | {ds.type} | {temporal} | {description} |\n")

    return "".join(lines)


def build_dataset_docs(public_only: bool = True) -> dict:
    from datasets.models import Dataset

    qs = Dataset.objects.prefetch_related("resources", "mappings").order_by("title", "name")
    if public_only:
        qs = qs.filter(public=True, active=True)

    out_dir: Path = settings.DOCS_DIR / "data_documentation" / "datasets"
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for ds in qs:
        slug = _slug(ds.name)
        page_path = out_dir / f"{slug}.md"
        page_path.write_text(_build_dataset_page(ds), encoding="utf-8")
        written.append(slug)

    index_path = out_dir / "index.md"
    index_path.write_text(_build_dataset_index(list(qs)), encoding="utf-8")

    logger.info("Dataset docs: wrote index + %d pages to %s", len(written), out_dir)
    return {"index": str(index_path), "pages": written}