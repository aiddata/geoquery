"""Attribution payloads for everything the MCP server hands back.

GeoQuery re-hosts open-access data. A chat client that shows a number without
naming where it came from strips the attribution the licence requires, and the
user never sees that it happened. So every payload that carries data or
describes a dataset or boundary embeds the structured ``attribution`` built
here, and ends its human-readable text with ``attribution["text"]`` -- the
model is instructed (see SERVER_INSTRUCTIONS) to relay both.

Missing metadata is reported, never omitted: an item with no recorded licence
keeps the ``license`` key set to ``None`` and gains a ``notes`` string saying
so, because "we don't know" is exactly what the user needs to hear before they
publish. ``manage.py report_missing_attribution`` lists what curation still
owes.
"""

from __future__ import annotations

from typing import Iterable

from geoquery.citations import (
    GEOQUERY_CITATION,
    GEOQUERY_DOI,
    GEOQUERY_URL,
    doi_from_citation,
)

NO_CITATION_NOTE = "citation not recorded; cite the source"
NO_LICENSE_NOTE = "license not recorded; check the source before redistributing"

_GEOQUERY = {
    "citation": GEOQUERY_CITATION,
    "doi": GEOQUERY_DOI,
    "url": GEOQUERY_URL,
}


def _item(obj) -> dict:
    """One attribution record for a Dataset or a FeatureCollection.

    Both models carry the same five attribution fields, so one shape covers
    them. Every key is always present -- consumers branch on ``None``, they
    never have to guess whether a missing key means "absent" or "unknown".
    """
    notes = [n for n in (
        None if obj.citation else NO_CITATION_NOTE,
        None if obj.license else NO_LICENSE_NOTE,
    ) if n]
    return {
        "name": obj.name,
        "title": obj.title or obj.name,
        "source_name": obj.source_name or None,
        "source_url": obj.source_url or None,
        "license": obj.license or None,
        "license_url": obj.license_url or None,
        "citation": obj.citation or None,
        "doi": doi_from_citation(obj.citation),
        "notes": "; ".join(notes) or None,
    }


def _compact(label: str, item: dict) -> str:
    """``Title (License)`` -- or, with no licence recorded, the source instead.

    The compact line is the part a chat client is most likely to actually
    repeat, so it never silently drops to just a title: without a licence it
    says so and points at where to look.
    """
    if item["license"]:
        return f"{label} ({item['license']})"
    source = item["source_name"]
    url = item["source_url"]
    if source and url:
        return f"{label} (license not recorded — source: {source}, {url})"
    if source:
        return f"{label} (license not recorded — source: {source})"
    if url:
        return f"{label} (license not recorded — source: {url})"
    return f"{label} (license not recorded)"


def _dedupe(labelled: list[tuple[str, dict]]) -> list[str]:
    """Compact strings in first-seen order, one per distinct label.

    A request over 30 geoBoundaries collections has one source and one licence;
    listing it 30 times would bury the datasets it sits next to.
    """
    seen: set[str] = set()
    out: list[str] = []
    for label, item in labelled:
        text = _compact(label, item)
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def attribution_for(
    datasets: Iterable = (), feature_collections: Iterable = ()
) -> dict:
    """Structured attribution for a set of datasets and boundaries.

    ``text`` is the one-line form to append to a tool's text content;
    ``datasets`` / ``boundaries`` are the structured records a client can
    render properly. Pass model instances -- the caller has normally already
    loaded them to resolve the selection.
    """
    ds_items = [_item(d) for d in datasets]
    fc_items = [_item(f) for f in feature_collections]

    parts = []
    if ds_items:
        # Datasets are named by title: that is how they are picked and how the
        # user thinks about them.
        joined = "; ".join(_dedupe([(i["title"], i) for i in ds_items]))
        parts.append(f"Data: {joined}")
    if fc_items:
        # Boundaries are named by provider: a selection is usually many
        # collections from one source under one licence.
        joined = "; ".join(
            _dedupe([(i["source_name"] or i["title"], i) for i in fc_items])
        )
        parts.append(f"Boundaries: {joined}")
    parts.append("Accessed via GeoQuery")

    return {
        "geoquery": dict(_GEOQUERY),
        "datasets": ds_items,
        "boundaries": fc_items,
        "text": " · ".join(parts),
    }


def attribution_for_request(request) -> dict:
    """Attribution for a finished export, from what the request actually used.

    Dataset names come from ``request.data["datasets"]`` (the submitted
    selection, which is what the results columns were built from) and the
    boundaries from the request's own extract tasks.
    """
    from datasets.models import Dataset

    names = [
        d.get("dataset_name")
        for d in (request.data or {}).get("datasets") or []
        if d.get("dataset_name")
    ]
    by_name = {d.name: d for d in Dataset.objects.filter(name__in=names)}
    # Preserve the submitted order, and skip a name whose Dataset row has since
    # been removed rather than inventing a placeholder record for it.
    ds = [by_name[n] for n in dict.fromkeys(names) if n in by_name]
    fcs = list(request.feature_collections().order_by("group_level", "name"))
    return attribution_for(ds, fcs)


def _reference(item: dict) -> str:
    """A reference-list entry for one item.

    ``citation`` is free text supplied by whoever curated the dataset, so it is
    passed through verbatim rather than reformatted -- reflowing someone else's
    reference into a house style is how citations get mangled. When there is no
    citation at all, a source-and-URL line stands in and the caller is told,
    via ``missing_citations``, that a human needs to check it.
    """
    if item["citation"]:
        return item["citation"]
    bits = [item["title"]]
    if item["source_name"]:
        bits.append(item["source_name"])
    if item["source_url"]:
        bits.append(item["source_url"])
    return ". ".join(bits) + f" [{NO_CITATION_NOTE}]"


def attribution_text(attr: dict, style: str = "apa") -> str:
    """Render ``attribution_for(...)`` as a reference list.

    ``style="apa"`` numbers the entries and appends the licence under each;
    ``style="plain"`` emits one unnumbered line per entry. Neither restyles a
    recorded citation: ``citation`` is a free-text field (structured author /
    year / DOI fields are a follow-up), so the only honest transformation is
    ordering and labelling.
    """
    items = [
        {
            "citation": attr["geoquery"]["citation"],
            "title": "GeoQuery",
            "source_name": "AidData",
            "source_url": attr["geoquery"]["url"],
            "license": None,
            "license_url": None,
            "doi": attr["geoquery"]["doi"],
            "notes": None,
        },
        *attr.get("datasets", []),
        *attr.get("boundaries", []),
    ]

    lines: list[str] = []
    for n, item in enumerate(items, 1):
        prefix = f"{n}. " if style == "apa" else ""
        lines.append(f"{prefix}{_reference(item)}")
        if item["license"]:
            license_line = f"License: {item['license']}"
            if item["license_url"]:
                license_line += f" ({item['license_url']})"
            lines.append(("   " if style == "apa" else "") + license_line)
    return "\n".join(lines)


def missing_attribution(attr: dict) -> dict:
    """Items in an attribution payload with no recorded citation or licence.

    Surfaced by ``get_citations`` so the user is told what they still have to
    look up themselves, instead of silently receiving a short reference list.
    """
    everything = [*attr.get("datasets", []), *attr.get("boundaries", [])]
    return {
        "missing_citation": [i["title"] for i in everything if not i["citation"]],
        "missing_license": [i["title"] for i in everything if not i["license"]],
    }
