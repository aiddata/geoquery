"""Finding boundaries and datasets, and seeing what is already processed.

Everything here is read-only and goes through ``catalog.access``, so a caller
sees exactly what they would see on the website: public resources plus
anything in a catalog they have been granted.

``list_available_data`` is the hub of the explore path. It answers the question
that decides everything after it -- "what can I have right now, without
waiting?" -- by splitting the catalog into what is already extracted for these
boundaries (``ready``) and what would have to be processed first
(``requestable``).
"""

from __future__ import annotations

from typing import Annotated

from django.db.models import Count, Q
from pydantic import Field

from analytics.models import Coverage, ExtractTask
from catalog.access import (
    filter_processing_options,
    visible_datasets,
    visible_feature_collections,
    visible_processing_options,
)
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, FeatureCollection
from features.search import search_feature_names
from mcp_server.data.attribution import (
    attribution_for,
    attribution_for_request,
    attribution_text,
    missing_attribution,
)
from mcp_server.schemas import BOUNDARIES_DESC, CitationStyle, GENERIC_OUTPUT_SCHEMA
from visualize.data import build_explore_available

from .common import READ_ONLY, fmt_count, result, tool_body

# A boundary name is gB_<release>_<ISO3>_<level>, so an ISO3 filter is an
# infix match on the delimited code -- not a prefix or a bare substring, which
# would also match e.g. "GHA" inside a release hash.
def _iso3_filter(iso3: str) -> Q:
    return Q(name__icontains=f"_{iso3.strip().upper()}_")


def _boundary_summary(fc: FeatureCollection) -> dict:
    return {
        "name": fc.name,
        "title": fc.title or fc.name,
        "description": fc.description,
        "group_title": fc.group_title or fc.group_name,
        "level": fc.group_level,
        "bbox": list(fc.spatial_extent.extent) if fc.spatial_extent else None,
        "tags": fc.tags or [],
        "source_name": fc.source_name,
        "license": fc.license,
    }


def _dataset_summary(ds: Dataset) -> dict:
    return {
        "name": ds.name,
        "title": ds.title or ds.name,
        "description": ds.description,
        "type": ds.type,
        "tags": ds.tags or [],
        "temporal_range": _temporal_range(ds),
        "source_name": ds.source_name,
        "license": ds.license,
    }


def _temporal_range(ds: Dataset) -> str | None:
    if not (ds.temporal_start or ds.temporal_end):
        return None
    start = ds.temporal_start.strftime("%Y") if ds.temporal_start else "?"
    end = ds.temporal_end.strftime("%Y") if ds.temporal_end else "?"
    return f"{start}–{end}"


# ── search_boundaries ────────────────────────────────────────────────────────


def _search_boundaries(user, query="", iso3=None, level=None, limit=20) -> dict:
    # User uploads are never public, so they are already excluded -- but say so
    # explicitly: an ephemeral custom boundary must not become selectable here
    # just because someone added it to a catalog.
    scope = visible_feature_collections(user).filter(is_user_upload=False)
    if iso3:
        scope = scope.filter(_iso3_filter(iso3))
    if level is not None:
        scope = scope.filter(group_level=level)

    qs = scope
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(title__icontains=query)
            | Q(description__icontains=query)
        )

    total = qs.count()
    results = list(qs.order_by("group_level", "name")[: max(1, limit)])
    # Collection titles only name countries, so on their own they cannot
    # answer "Nairobi" or "Kumasi". The districts and regions inside the
    # collections can, within the same iso3/level scope.
    places = search_feature_names(scope, query, max(1, limit))
    cited = {fc.id: fc for fc in results}
    for fm in places.matches:
        cited.setdefault(fm.fc_id, fm.fc)
    return {
        "boundaries": [_boundary_summary(fc) for fc in results],
        "total_matching": total,
        "truncated": total > len(results),
        "places": [_place_summary(fm) for fm in places.matches],
        "places_truncated": places.truncated,
        "places_approximate": places.approximate,
        "attribution": attribution_for([], cited.values()),
    }


def _place_summary(fm: FeatMap) -> dict:
    return {
        "name": fm.name,
        "feature_id": fm.geom_id,
        "boundary": fm.fc.name,
        "boundary_title": fm.fc.title or fm.fc.name,
        "level": fm.fc.group_level,
    }


def _search_boundaries_lines(query: str, payload: dict) -> list[str]:
    boundaries, places = payload["boundaries"], payload["places"]
    found = payload["total_matching"]
    lines = [
        f"{fmt_count(found, 'boundary set', 'boundary sets')} matched"
        + (f"; showing {len(boundaries)}." if payload["truncated"] else ".")
    ]
    for fc in boundaries:
        lines.append(
            f"- {fc['name']}: {fc['title']}"
            + (f" (level {fc['level']})" if fc["level"] is not None else "")
        )

    if places:
        if payload["places_approximate"]:
            lines.append(f"No place is named '{query}'; closest spellings:")
        elif payload["places_truncated"]:
            lines.append(
                f"Places named like '{query}' (more exist; narrow with iso3 or level):"
            )
        else:
            lines.append(f"Places named like '{query}':")
        for place in places:
            lines.append(
                f"- {place['name']} [feature {place['feature_id']}] in "
                f"{place['boundary']} ({place['boundary_title']}"
                + (f", level {place['level']})" if place["level"] is not None else ")")
            )
        lines.append(
            "A place is one feature of its boundary set. Pass that set as "
            "boundaries=[...] to list_available_data, then read just this place "
            "with get_data(search='<place name>'), or export it with "
            "preview_request(boundary=..., feature_ids=[...])."
        )
    elif query and not boundaries:
        # Without this a model given "Nairobi" -> nothing has no idea whether
        # GeoQuery lacks Kenya or merely lacks the word, and usually gives up.
        lines.append(
            f"Nothing matched '{query}'. This searches country names, ISO3 "
            "codes and the names of administrative areas (regions, "
            "districts) -- not towns, neighbourhoods or landmarks. If this "
            "is a town, search for the district or region it lies in, or for "
            "its country by name or iso3= (e.g. iso3='KEN')."
        )
    return lines


# ── get_boundary ─────────────────────────────────────────────────────────────

_FEATURE_PREVIEW = 10


def _get_boundary(user, name: str) -> dict:
    fc = visible_feature_collections(user).filter(name=name).first()
    if fc is None:
        from mcp_server.data.selection import SelectionError

        raise SelectionError(
            f"No boundary available named '{name}'. Use search_boundaries to "
            "find the exact name."
        )

    feature_count = FeatMap.objects.filter(fc=fc).count()
    preview = list(
        FeatMap.objects.filter(fc=fc)
        .order_by("name", "geom_id")
        .values("geom_id", "name")[:_FEATURE_PREVIEW]
    )
    return {
        **_boundary_summary(fc),
        "details": fc.details,
        "source_url": fc.source_url,
        "license_url": fc.license_url,
        "citation": fc.citation,
        "feature_count": feature_count,
        "features_preview": [
            {"feature_id": row["geom_id"], "name": row["name"]} for row in preview
        ],
        "attribution": attribution_for([], [fc]),
    }


# ── search_datasets ──────────────────────────────────────────────────────────


def _search_datasets(user, query="", tag=None, type=None, limit=20) -> dict:
    qs = visible_datasets(user)
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(title__icontains=query)
            | Q(description__icontains=query)
        )
    if tag:
        qs = qs.filter(tags__contains=[tag])
    if type:
        qs = qs.filter(type=type)

    total = qs.count()
    results = list(qs.order_by("title", "name")[: max(1, limit)])
    return {
        "datasets": [_dataset_summary(ds) for ds in results],
        "total_matching": total,
        "truncated": total > len(results),
        "attribution": attribution_for(results, []),
    }


# ── get_dataset ──────────────────────────────────────────────────────────────

# A dataset can have thousands of resources (one per day for two decades).
# Listing them all would swamp the model's context to no purpose, so the cap
# is a hard one and the tool says when it bit.
_MAX_RESOURCES = 500


def _get_dataset(user, name: str, include_resources: bool = False) -> dict:
    ds = visible_datasets(user).filter(name=name).first()
    if ds is None:
        from mcp_server.data.selection import SelectionError

        raise SelectionError(
            f"No dataset available named '{name}'. Use search_datasets to find "
            "the exact name."
        )

    options = sorted(
        filter_processing_options(user, ds.processing_options.all()),
        key=lambda po: po.short_name,
    )
    other = ds.other if isinstance(ds.other, dict) else {}
    resource_count = ds.resources.count()

    payload = {
        **_dataset_summary(ds),
        "details": ds.details,
        "variable_description": ds.variable_description,
        "source_url": ds.source_url,
        "license_url": ds.license_url,
        "citation": ds.citation,
        "extract_types": [
            {"short_name": po.short_name, "description": po.description or ""}
            for po in options
        ],
        "filters": other.get("filters"),
        "outcomes": other.get("outcomes"),
        "resource_count": resource_count,
        "attribution": attribution_for([ds], []),
    }

    if include_resources:
        resources = list(
            ds.resources.order_by("temporal", "name").values("name", "label", "temporal")[
                :_MAX_RESOURCES
            ]
        )
        payload["resources"] = [
            {
                "name": r["name"],
                "label": r["label"],
                "year": r["temporal"].year if r["temporal"] else None,
            }
            for r in resources
        ]
        payload["resources_truncated"] = resource_count > len(resources)

    return payload


# Enough to name every requestable dataset in a typical catalog without
# letting a pathological one fill the model's context.
_REQUESTABLE_NAMES = 60


# ── list_available_data ──────────────────────────────────────────────────────


def _list_available_data(user, boundaries: list[str]) -> dict:
    from mcp_server.data.selection import _resolve_boundaries

    fcs = _resolve_boundaries(user, boundaries)
    fc_ids = [fc.id for fc in fcs]
    po_ids = list(visible_processing_options(user).values_list("id", flat=True))

    ready = build_explore_available(fc_ids, po_ids)
    ready_dataset_ids = {entry["dataset_id"] for entry in ready}

    datasets = {
        d.id: d for d in Dataset.objects.filter(id__in=ready_dataset_ids)
    }
    resource_counts = dict(
        DatasetResource.objects.filter(dataset_id__in=ready_dataset_ids)
        .values("dataset_id")
        .annotate(n=Count("id"))
        .values_list("dataset_id", "n")
    )
    coverage = _coverage_fractions(fc_ids, ready_dataset_ids, po_ids)

    ready_payload = []
    for entry in ready:
        ds = datasets.get(entry["dataset_id"])
        if ds is None:
            continue
        ready_payload.append(
            {
                "dataset": ds.name,
                "title": ds.title or ds.name,
                "extract_types": [o["short_name"] for o in entry["options"]],
                "extract_type_descriptions": {
                    o["short_name"]: o["description"] for o in entry["options"]
                },
                "resource_count": resource_counts.get(ds.id, 0),
                "temporal_range": _temporal_range(ds),
                "coverage_fraction": coverage.get(ds.id, 0.0),
                "source_name": ds.source_name,
                "license": ds.license,
            }
        )

    requestable = _requestable_datasets(user, fc_ids, ready_dataset_ids)

    return {
        "boundaries": [fc.name for fc in fcs],
        "feature_count": FeatMap.objects.filter(fc_id__in=fc_ids).count(),
        "ready": ready_payload,
        "requestable": [_dataset_summary(ds) for ds in requestable],
        # In the order `ready` presents them, not set order, so the same
        # selection always cites its sources the same way round.
        "attribution": attribution_for(
            [
                datasets[entry["dataset_id"]]
                for entry in ready
                if entry["dataset_id"] in datasets
            ],
            fcs,
        ),
    }


def _coverage_fractions(
    fc_ids: list[int], dataset_ids: set[int], po_ids: list[int]
) -> dict[int, float]:
    """Fraction of each boundary's features with a completed extract.

    A dataset can be "available" while only part of a selection is processed
    -- a country only half requested. The model needs that number before it
    describes a map as showing a country.

    "Completed" is not "has a value": a nodata result (a feature smaller than
    a pixel, or past a raster's edge) is a completed extract and counts here.
    Telling those apart means reading extract_data, which this summary of
    every ready dataset deliberately avoids; get_data and show_map report it
    per column from the values they already load. Likewise a feature counts
    once any year is processed -- per-year gaps are also theirs to report.

    Only the caller's visible extract types count, matching `ready`: a
    feature processed solely for a private extract type is not one this
    caller can read.

    Read from a standby: a fraction a few seconds behind the primary is still
    the right answer to "how much of this is processed", and the extract_tasks
    count is heavy.
    """
    if not dataset_ids:
        return {}
    total = FeatMap.objects.using("replica").filter(fc_id__in=fc_ids).count()
    if not total:
        return {ds_id: 0.0 for ds_id in dataset_ids}

    done = dict(
        ExtractTask.objects.using("replica").filter(
            fm__fc_id__in=fc_ids,
            dataset_id__in=dataset_ids,
            po_id__in=po_ids,
            status=1,
        )
        .values("dataset_id")
        .annotate(n=Count("fm_id", distinct=True))
        .values_list("dataset_id", "n")
    )
    return {ds_id: round(done.get(ds_id, 0) / total, 3) for ds_id in dataset_ids}


def _requestable_datasets(user, fc_ids: list[int], ready_dataset_ids: set[int]):
    """Visible datasets that *could* cover these boundaries but have no extracts.

    "Could cover" is either global coverage or a Coverage row for one of these
    features. Without that filter the list would include every dataset in the
    catalog, and exporting one that does not reach this area produces nothing.
    """
    geom_ids = FeatMap.objects.filter(fc_id__in=fc_ids).values("geom_id")
    return list(
        visible_datasets(user)
        .filter(
            Q(is_global=True)
            | Q(
                id__in=Coverage.objects.filter(geom_id__in=geom_ids).values(
                    "dataset_id"
                )
            )
        )
        .exclude(id__in=ready_dataset_ids)
        .order_by("title", "name")
    )


# ── get_citations ────────────────────────────────────────────────────────────


def _get_citations(
    user, datasets=None, boundaries=None, request_id=None, style="apa"
) -> dict:
    from mcp_server.data.selection import SelectionError, _resolve_request

    if request_id:
        attribution = attribution_for_request(_resolve_request(request_id))
    else:
        ds = list(visible_datasets(user).filter(name__in=datasets or []))
        fcs = list(visible_feature_collections(user).filter(name__in=boundaries or []))
        if not ds and not fcs:
            raise SelectionError(
                "Nothing to cite. Pass datasets=[...], boundaries=[...], or "
                "request_id=."
            )
        attribution = attribution_for(ds, fcs)

    missing = missing_attribution(attribution)
    return {
        "references": attribution_text(attribution, style=style),
        "licenses": [
            {
                "name": item["title"],
                "license": item["license"],
                "license_url": item["license_url"],
                "source_name": item["source_name"],
                "source_url": item["source_url"],
            }
            for item in (*attribution["datasets"], *attribution["boundaries"])
        ],
        "missing_citation": missing["missing_citation"],
        "missing_license": missing["missing_license"],
        "attribution": attribution,
    }


# ── registration ─────────────────────────────────────────────────────────────


def register(mcp, user_dep):
    @mcp.tool(annotations=READ_ONLY, output_schema=GENERIC_OUTPUT_SCHEMA)
    @tool_body
    def search_boundaries(
        query: Annotated[
            str,
            Field(
                description=(
                    "A country, region or district name, e.g. 'Ghana' or "
                    "'Kumasi'. Matched against boundary sets and against the "
                    "names of the areas inside them; case and accents are "
                    "ignored."
                )
            ),
        ] = "",
        iso3: Annotated[
            str | None, Field(description="ISO3 country code, e.g. 'GHA'.")
        ] = None,
        level: Annotated[
            int | None,
            Field(description="Administrative level: 0 country, 1 region, 2 district."),
        ] = None,
        limit: Annotated[int, Field(description="Maximum results.", ge=1, le=200)] = 20,
        user=user_dep,
    ):
        """Find GeoQuery boundaries by place: look up a country, region,
        province, district or city and get the administrative boundaries
        that cover it.

        Start here: every other GeoQuery tool takes boundaries by the `name`
        this returns. A country name matches boundary sets directly
        (`boundaries`). A region or district name matches the administrative
        areas inside them (`places`): each place gives the boundaries it
        belongs to and its `feature_id`. Narrow with `iso3` and `level` when
        you already know the country and how fine a breakdown you need.

        Only administrative areas are named here, not towns or landmarks;
        a city is usually found as the district of the same name.
        """
        payload = _search_boundaries(user, query, iso3, level, limit)
        return result(_search_boundaries_lines(query, payload), payload)

    @mcp.tool(annotations=READ_ONLY, output_schema=GENERIC_OUTPUT_SCHEMA)
    @tool_body
    def get_boundary(
        name: Annotated[str, Field(description="Feature collection name.")],
        user=user_dep,
    ):
        """Details of one boundary set: how many features, a sample of their
        names and ids, and its source and license.

        Results include `attribution`; relay the sources, licenses and
        citations to the user.
        """
        payload = _get_boundary(user, name)
        lines = [
            f"{payload['title']} ({payload['name']}) — "
            f"{fmt_count(payload['feature_count'], 'feature')}.",
            payload.get("description") or "",
        ]
        preview = payload["features_preview"]
        if preview:
            lines.append(
                f"Features (first {len(preview)} by name): "
                + ", ".join(f"{f['name']} [{f['feature_id']}]" for f in preview)
                + ("…" if payload["feature_count"] > len(preview) else "")
            )
        if payload.get("source_name") or payload.get("license"):
            lines.append(
                f"Source: {payload.get('source_name') or 'not recorded'}; "
                f"license: {payload.get('license') or 'not recorded'}."
            )
        return result(lines, payload)

    @mcp.tool(annotations=READ_ONLY, output_schema=GENERIC_OUTPUT_SCHEMA)
    @tool_body
    def search_datasets(
        query: Annotated[str, Field(description="Text to match.")] = "",
        tag: Annotated[str | None, Field(description="Exact tag, e.g. 'climate'.")] = None,
        type: Annotated[
            str | None, Field(description="Dataset type, e.g. 'raster' or 'vector'.")
        ] = None,
        limit: Annotated[int, Field(description="Maximum results.", ge=1, le=200)] = 20,
        user=user_dep,
    ):
        """Search the dataset catalog.

        This searches everything GeoQuery holds, whether or not it is already
        processed for a particular place. To find what you can read *right
        now* for specific boundaries, use list_available_data instead.
        """
        payload = _search_datasets(user, query, tag, type, limit)
        lines = [
            f"{fmt_count(payload['total_matching'], 'dataset')} matched"
            + (f"; showing {len(payload['datasets'])}." if payload["truncated"] else ".")
        ]
        for ds in payload["datasets"]:
            lines.append(
                f"- {ds['name']}: {ds['title']}"
                + (f" ({ds['temporal_range']})" if ds["temporal_range"] else "")
            )
        return result(lines, payload)

    @mcp.tool(annotations=READ_ONLY, output_schema=GENERIC_OUTPUT_SCHEMA)
    @tool_body
    def get_dataset(
        name: Annotated[str, Field(description="Dataset name.")],
        include_resources: Annotated[
            bool,
            Field(
                description=(
                    "Include the individual resource (per-year/per-file) names. "
                    "Capped at 500; leave off unless you need exact names."
                )
            ),
        ] = False,
        user=user_dep,
    ):
        """What a dataset measures, which extract types it offers, what years
        it spans, and how to cite it.

        The `extract_types` are the values `get_data`'s `extract_type`
        argument accepts. Results include `attribution`; relay the sources,
        licenses and citations to the user.
        """
        payload = _get_dataset(user, name, include_resources)
        lines = [
            f"{payload['title']} ({payload['name']}) — {payload['type']}, "
            f"{fmt_count(payload['resource_count'], 'resource')}"
            + (f", {payload['temporal_range']}." if payload["temporal_range"] else "."),
            payload.get("description") or "",
            "Extract types: "
            + (
                ", ".join(e["short_name"] for e in payload["extract_types"])
                or "(none configured)"
            ),
        ]
        return result(lines, payload)

    @mcp.tool(annotations=READ_ONLY, output_schema=GENERIC_OUTPUT_SCHEMA)
    @tool_body
    def list_available_data(
        boundaries: Annotated[list[str], Field(description=BOUNDARIES_DESC)],
        user=user_dep,
    ):
        """What data is available for these boundaries, split by how you can
        get it.

        `ready` is already processed and readable immediately with get_data or
        show_map -- prefer it. `coverage_fraction` is the share of the
        boundary's features processed for at least one year; well under 1.0
        means only part of this area has been processed. It does not mean
        every feature has a value: get_data and show_map report, per column,
        features not yet processed for that year and features the source has
        no data for (e.g. smaller than a pixel).

        `requestable` would have to be processed first, via preview_request
        and submit_request, which takes minutes to hours.

        Results include `attribution`; relay the sources, licenses and
        citations to the user.
        """
        payload = _list_available_data(user, boundaries)
        lines = [
            f"{fmt_count(len(payload['ready']), 'dataset')} ready to read now, "
            f"{len(payload['requestable'])} more available by export, across "
            f"{fmt_count(payload['feature_count'], 'feature')}.",
        ]
        for entry in payload["ready"]:
            lines.append(
                f"- {entry['dataset']} [{', '.join(entry['extract_types'])}]"
                + (f" {entry['temporal_range']}" if entry["temporal_range"] else "")
                + f" — {entry['coverage_fraction']:.0%} of features processed"
            )
        requestable = payload["requestable"]
        if requestable:
            # Named, not just counted: "37 more available by export" is not
            # something a model can offer the user, and the names are the
            # cheapest part of the payload.
            shown = requestable[:_REQUESTABLE_NAMES]
            lines.append(
                "Requestable by export (not processed for these boundaries "
                "yet): "
                + ", ".join(ds["name"] for ds in shown)
                + (
                    f", and {len(requestable) - len(shown)} more — "
                    "search_datasets lists them all."
                    if len(requestable) > len(shown)
                    else "."
                )
            )
        return result(lines, payload)

    @mcp.tool(annotations=READ_ONLY, output_schema=GENERIC_OUTPUT_SCHEMA)
    @tool_body
    def get_citations(
        datasets: Annotated[
            list[str] | None, Field(description="Dataset names to cite.")
        ] = None,
        boundaries: Annotated[
            list[str] | None, Field(description="Boundary names to cite.")
        ] = None,
        request_id: Annotated[
            str | None,
            Field(description="Cite everything a finished export used."),
        ] = None,
        style: Annotated[
            CitationStyle,
            Field(description="'apa' numbers the entries; 'plain' does not."),
        ] = "apa",
        user=user_dep,
    ):
        """Citations and licenses for the data you used, as a formatted
        reference list.

        Also names the items with no recorded citation or license -- tell the
        user about those explicitly, because they have to check the source
        themselves before publishing.
        """
        payload = _get_citations(user, datasets, boundaries, request_id, style)
        lines = [payload["references"]]
        if payload["missing_citation"]:
            lines.append(
                "No citation recorded for: "
                + ", ".join(payload["missing_citation"])
                + " — check the source before publishing."
            )
        if payload["missing_license"]:
            lines.append(
                "No license recorded for: " + ", ".join(payload["missing_license"]) + "."
            )
        return result(lines, payload)
