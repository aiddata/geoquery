"""Markdown for the data documentation pages. Pure functions of model objects."""

import re

from .coverage import FULL
from .grouping import gb_version
from .text import (
    cell,
    date_range,
    front_matter,
    join_words,
    license_text,
    link,
    meta_description,
    one_line,
    slug,
    year_range,
)

DATASET_SUFFIX = " Free to extract with AidData GeoQuery."
GEOBOUNDARIES_URL = "https://www.geoboundaries.org"

# Tag -> phrase, in the order a boundary page's description names them.
TOPICS = (
    ("population", "population"),
    ("nighttimelights", "nighttime lights"),
    ("malaria", "malaria"),
    ("conflict", "conflict"),
    ("precipitation", "rainfall"),
    ("temperature", "temperature"),
    ("air quality", "air quality"),
    ("land cover", "land cover"),
    ("landcover", "land cover"),
)


def topics(datasets, limit: int = 4) -> list:
    tags = {tag for ds in datasets for tag in (ds.tags or [])}
    found = []
    for tag, phrase in TOPICS:
        if tag in tags and phrase not in found:
            found.append(phrase)
    return found[:limit]


def _table(rows) -> str:
    rows = [(label, value) for label, value in rows if value]
    if not rows:
        return ""
    return "| | |\n|---|---|\n" + "".join(f"| {label} | {value} |\n" for label, value in rows) + "\n"


def _label(text) -> str:
    """A link label: a table-safe cell with square brackets escaped."""
    return cell(text).replace("[", "\\[").replace("]", "\\]")


def _heading(text) -> str:
    """Heading text on one line, without braces that could split a ``{#id}``."""
    return one_line(text).replace("{", "").replace("}", "")


def _prose(text) -> str:
    """Free text as plain paragraphs: no tables, headings or other block syntax."""
    paragraphs = (one_line(p) for p in re.split(r"\n\s*\n", str(text or "")))
    return "\n\n".join(f"\\{p}" if p.startswith("#") else p for p in paragraphs if p)


def _source(name, url) -> str:
    if name:
        return link(_label(name), url)
    return link(_label(url), url) if url else ""


def _coverage_label(status) -> str:
    return "Full" if status == FULL else "Partial"


def _title(obj) -> str:
    return obj.title or obj.name


def dataset_page(ds, available) -> str:
    """``available``: [(Page, status)] in display order; unused for global datasets."""
    title = _title(ds)
    out = [front_matter(meta_description(f"{title}.", ds.description, DATASET_SUFFIX)), f"# {_heading(title)}\n\n"]
    if ds.description:
        out.append(f"{one_line(ds.description)}\n\n")
    if ds.details:
        out.append(f"{_prose(ds.details)}\n\n")

    variable = cell(ds.variable_description) if ds.variable_description else ""
    if variable and ds.variable_factor not in (None, 1.0):
        variable += f" (factor: {ds.variable_factor})"
    has_period = ds.temporal_start or ds.temporal_end
    out.append("## Details\n\n")
    out.append(_table([
        ("Type", cell(ds.type)),
        (cell(ds.temporal_name or "Time period"), date_range(ds.temporal_start, ds.temporal_end) if has_period else ""),
        ("Temporal type", cell(ds.temporal_type) if ds.temporal_type else ""),
        ("Tags", cell(", ".join(ds.tags)) if ds.tags else ""),
        ("Variable", variable),
        ("Source", _source(ds.source_name, ds.source_url)),
        ("License", license_text(ds)),
    ]))

    out.append("## Available for\n\n")
    if ds.is_global:
        out.append("Every boundary in GeoQuery.\n\n")
    elif available:
        out.append("| Boundaries | Coverage |\n|---|---|\n")
        out.extend(
            f"| [{_label(page.title)}](../boundaries/{page.slug}.md) | {_coverage_label(status)} |\n"
            for page, status in available
        )
        out.append("\n")
    else:
        out.append("No boundaries in GeoQuery are within this dataset's coverage yet.\n\n")

    resources = list(ds.resources.all())
    if resources:
        out.append("## Resources\n\n| Name | Label | Date |\n|---|---|---|\n")
        out.extend(
            f"| {cell(r.name)} | {cell(r.label)} | {f'{r.temporal:%Y-%m-%d}' if r.temporal else '—'} |\n"
            for r in resources
        )
        out.append("\n")
    mappings = list(ds.mappings.all())
    if mappings:
        out.append("## Value Mappings\n\n| Value | Label |\n|---|---|\n")
        out.extend(f"| {m.map_val} | {cell(m.map_name)} |\n" for m in mappings)
        out.append("\n")
    if ds.citation:
        out.append(f"## Citation\n\n{one_line(ds.citation)}\n")
    return "".join(out)


def _collection_block(fc, depth: int, feature_count: int, geoboundaries: bool, show_description: bool) -> str:
    out = [f"{'#' * depth} {_heading(_title(fc))} {{#{slug(fc.name)}}}\n\n"]
    if fc.description and show_description:
        out.append(f"{one_line(fc.description)}\n\n")
    if fc.details:
        out.append(f"{_prose(fc.details)}\n\n")
    version = gb_version(fc) if geoboundaries else None
    has_period = fc.temporal_start or fc.temporal_end
    out.append(_table([
        ("Features", f"{feature_count:,}"),
        ("geoBoundaries version", cell(version) if version else ""),
        ("Added to GeoQuery", f"{fc.date_added:%Y-%m-%d}" if fc.date_added else ""),
        (cell(fc.temporal_name or "Time period"), year_range(fc.temporal_start, fc.temporal_end) if has_period else ""),
        ("Source", _source(fc.source_name, fc.source_url)),
        ("License", license_text(fc)),
    ]))
    return "".join(out)


def _boundary_description(lead, datasets) -> str:
    """The lead, then as much of the dataset sentence as fits in a meta
    description: every topic it can name, fewer for a long place name, else
    just the count. No brand suffix -- the page title already carries it, and
    the place and its data types are what a search should match."""
    if not datasets:
        return meta_description(lead)
    n = len(datasets)
    found = topics(datasets)
    for k in range(len(found), -1, -1):
        detail = f"Free to extract with GeoQuery: {n} dataset{'' if n == 1 else 's'}"
        detail += f", including {join_words(found[:k])}." if k else "."
        description = meta_description(lead, detail)
        if description.endswith(detail):
            return description
    return meta_description(lead)


def boundary_page(page, covering, feature_counts, app_url) -> str:
    """``covering``: [(Dataset, status)] in display order."""
    datasets = [ds for ds, _ in covering]
    if page.geoboundaries:
        levels = _levels(page).replace("–", " to ")
        lead = f"{page.place} administrative boundaries ({levels})."
        intro = (
            f"Administrative boundaries for {page.place} from [geoBoundaries]({GEOBOUNDARIES_URL}), "
            f"ready to use in [GeoQuery]({app_url}) to extract data for each area.\n\n"
        )
    else:
        n = len(page.collections)
        lead = f"{page.title}: {n} boundary set{'' if n == 1 else 's'}."
        newest = max(page.collections, key=lambda fc: fc.date_added)
        intro = f"{one_line(newest.description)}\n\n" if newest.description else ""
    out = [front_matter(_boundary_description(lead, datasets)), f"# {_heading(page.title)}\n\n", intro]
    show_description = not page.geoboundaries and len(page.collections) > 1
    for heading, members in page.sections():
        depth = 2
        if heading:
            out.append(f"## {_heading(heading)} {{#{slug(heading.split(' (')[0])}}}\n\n")
            depth = 3
        for fc in members:
            out.append(_collection_block(fc, depth, feature_counts.get(fc.id, 0), page.geoboundaries, show_description))

    # Out of the site search: every boundary page lists the same datasets, so
    # indexing them buried each dataset's own page under ~235 boundary pages.
    out.append(f"## Datasets for {_heading(page.place)} {{#datasets data-search-exclude}}\n\n")
    if covering:
        out.append("| Dataset | Time period | Coverage |\n|---|---|---|\n")
        out.extend(
            f"| [{_label(_title(ds))}](../datasets/{slug(ds.name)}.md) | "
            f"{year_range(ds.temporal_start, ds.temporal_end)} | {_coverage_label(status)} |\n"
            for ds, status in covering
        )
        out.append("\n")
    else:
        out.append("No datasets in GeoQuery cover these boundaries yet.\n\n")

    citations = list(dict.fromkeys(one_line(fc.citation) for fc in page.collections if fc.citation))
    if citations:
        out.append("## Citation\n\n" + "\n\n".join(citations) + "\n")
    return "".join(out)


def _filter_box(label: str, noun: str) -> str:
    """A filter for the page's tables; docs/javascripts/table-filter.js wires it up."""
    return (
        f'<div class="gq-filter" data-noun="{noun}">'
        f'<input type="search" placeholder="{label}" aria-label="{label}" autocomplete="off">'
        '<span class="gq-filter-count" aria-live="polite"></span>'
        "</div>\n\n"
    )


# Hand-written framing for the two index pages. Deliberately general, so it
# stays true as datasets and boundary sets come and go; the tables below it
# carry the specifics.
DATASETS_OVERVIEW = """\
GeoQuery's datasets are global and regional data layers that you can summarize for any boundary you select. They span topics such as population, economic activity, climate, the environment, health, conflict and natural resources, and new datasets are added over time.

Datasets are either rasters, grids of values from satellite imagery, models or surveys, or are made of points or shapes, such as recorded events. Many are time series, so you can choose the years or months you need.

The table below lists every dataset currently available. Select one for its description, coverage, source and citation.

"""

BOUNDARIES_OVERVIEW = f"""\
Boundaries are the areas GeoQuery summarizes data for: each one becomes a row in your results.

- **Country administrative boundaries** come from [geoBoundaries]({GEOBOUNDARIES_URL}), an open database of political boundaries. Each country has levels from ADM0, its national border, down to finer units: ADM1 is usually provinces or states, ADM2 districts or counties, and some countries go further. Which levels are available differs by country.
- **Other boundary sets** cover areas beyond administrative divisions, such as city extents, or come from other sources.
- **Your own boundaries** can be uploaded as a custom boundary file in GeoQuery.

You can select several boundary sets in one request, or pick individual areas within one set. Select a country or boundary set for its levels, feature counts, source and the datasets available for it.

"""


def datasets_index(datasets) -> str:
    out = [
        front_matter(
            f"All {len(datasets)} datasets in AidData GeoQuery: population, nighttime lights, "
            "climate, land cover, conflict, health and more, free to extract for any boundary."
        ),
        "# Datasets\n\n",
        DATASETS_OVERVIEW,
        _filter_box("Filter datasets by name, type, license or description", "datasets"),
        "| Dataset | Type | Time period | License | Description |\n|---|---|---|---|---|\n",
    ]
    for ds in sorted(datasets, key=lambda d: _title(d).lower()):
        description = one_line(ds.description)
        if len(description) > 120:
            description = description[:119].rsplit(" ", 1)[0] + "…"
        out.append(
            f"| [{_label(_title(ds))}]({slug(ds.name)}.md) | {cell(ds.type)} | "
            f"{year_range(ds.temporal_start, ds.temporal_end)} | {cell(ds.license) if ds.license else 'Not recorded'} | {cell(description)} |\n"
        )
    return "".join(out)


def _levels(page) -> str:
    levels = sorted({fc.group_level for fc in page.collections if fc.group_level is not None})
    if not levels:
        return "—"
    return f"ADM{levels[0]}" if len(levels) == 1 else f"ADM{levels[0]}–ADM{levels[-1]}"


def boundaries_index(pages) -> str:
    countries = [p for p in pages if p.geoboundaries]
    others = [p for p in pages if not p.geoboundaries]
    out = [
        front_matter(
            f"Boundaries in AidData GeoQuery: administrative boundaries for {len(countries)} "
            f"countries from geoBoundaries, plus {len(others)} other boundary {'set' if len(others) == 1 else 'sets'}."
        ),
        "# Boundaries\n\n",
        BOUNDARIES_OVERVIEW,
        _filter_box("Filter by country, level or boundary set", "boundaries"),
    ]
    if countries:
        out.append(f"## Countries\n\nAdministrative boundaries from [geoBoundaries]({GEOBOUNDARIES_URL}).\n\n")
        out.append("| Country | Levels |\n|---|---|\n")
        out.extend(f"| [{_label(p.place)}]({p.slug}.md) | {_levels(p)} |\n" for p in countries)
        out.append("\n")
    if others:
        out.append("## Other boundary sets\n\n| Boundaries | Collections | Source |\n|---|---|---|\n")
        out.extend(
            f"| [{_label(p.title)}]({p.slug}.md) | {len(p.collections)} | {cell(p.collections[0].source_name)} |\n"
            for p in others
        )
    return "".join(out)
