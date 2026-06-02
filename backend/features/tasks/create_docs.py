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


def _build_fc_page(fc, feature_count: int) -> str:
    lines = []

    lines.append(f"# {fc.title or fc.name}\n")

    if fc.description:
        lines.append(f"{fc.description}\n")

    if fc.details:
        lines.append(f"{fc.details}\n")

    lines.append("## Details\n")
    lines.append("| | |\n|---|---|\n")
    lines.append(f"| Features | {feature_count:,} |\n")

    if fc.group_title or fc.group_name:
        lines.append(f"| Group | {fc.group_title or fc.group_name} |\n")
    if fc.group_level is not None:
        lines.append(f"| Administrative level | {fc.group_level} |\n")
    if fc.group_class:
        lines.append(f"| Class | {fc.group_class} |\n")
    if fc.is_global:
        lines.append("| Coverage | Global |\n")

    if fc.temporal_start or fc.temporal_end:
        start = fc.temporal_start.strftime("%Y-%m-%d") if fc.temporal_start else "—"
        end = fc.temporal_end.strftime("%Y-%m-%d") if fc.temporal_end else "—"
        label = fc.temporal_name or "Temporal range"
        lines.append(f"| {label} | {start} – {end} |\n")

    if fc.temporal_type:
        lines.append(f"| Temporal type | {fc.temporal_type} |\n")

    if fc.tags:
        lines.append(f"| Tags | {', '.join(fc.tags)} |\n")

    if fc.source_name:
        url = _absolute_url(fc.source_url or "")
        if url:
            lines.append(f"| Source | [{fc.source_name}]({url}) |\n")
        else:
            lines.append(f"| Source | {fc.source_name} |\n")

    if fc.citation:
        lines.append("\n## Citation\n")
        lines.append(f"{fc.citation}\n")

    return "".join(lines)


def _build_fc_index(fcs, counts: dict) -> str:
    lines = ["# Boundaries\n\n"]
    lines.append(
        "This page lists all boundary datasets available in GeoQuery. "
        "Click a boundary name for full details.\n\n"
    )
    lines.append("| Boundary | Group | Level | Features | Description |\n")
    lines.append("|---|---|---|---|---|\n")

    for fc in fcs:
        slug = _slug(fc.name)
        name_link = f"[{fc.title or fc.name}]({slug}.md)"
        group = fc.group_title or fc.group_name or "—"
        level = str(fc.group_level) if fc.group_level is not None else "—"
        count = f"{counts.get(fc.id, 0):,}"
        description = (fc.description or "").replace("|", "\\|")[:120]
        if len(fc.description or "") > 120:
            description += "…"
        lines.append(f"| {name_link} | {group} | {level} | {count} | {description} |\n")

    return "".join(lines)


def build_boundary_docs(public_only: bool = True) -> dict:
    from django.db.models import Count
    from features.models import FeatureCollection, FeatMap

    qs = FeatureCollection.objects.order_by("group_level", "title", "name")
    if public_only:
        qs = qs.filter(public=True, active=True)

    fc_list = list(qs)
    fc_ids = [fc.id for fc in fc_list]

    counts = dict(
        FeatMap.objects.filter(fc_id__in=fc_ids)
        .values("fc_id")
        .annotate(n=Count("id"))
        .values_list("fc_id", "n")
    )

    out_dir: Path = settings.DOCS_DIR / "data_documentation" / "boundaries"
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for fc in fc_list:
        slug = _slug(fc.name)
        page_path = out_dir / f"{slug}.md"
        page_path.write_text(_build_fc_page(fc, counts.get(fc.id, 0)), encoding="utf-8")
        written.append(slug)

    index_path = out_dir / "index.md"
    index_path.write_text(_build_fc_index(fc_list, counts), encoding="utf-8")

    logger.info("Boundary docs: wrote index + %d pages to %s", len(written), out_dir)
    return {"index": str(index_path), "pages": written}