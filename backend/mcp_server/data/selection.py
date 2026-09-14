"""Turning a tool's arguments into a set of rows.

``get_data``, ``show_map``, ``get_citations`` and the CSV resource all describe
the same thing -- some boundaries crossed with some data -- and all have to
apply the same visibility rules and reach the same payload builder. Resolving
that once, here, is what keeps a map and the table beside it showing the same
numbers.

Two sources feed a selection, and they are mutually exclusive:

* **explore** (``boundaries`` + ``dataset``): the pre-processed extracts that
  already exist, read live. This is the fast path and the one most questions
  should take.
* **request** (``request_id``): a finished export. Its columns are fixed at
  what was submitted, so the dataset/year arguments do not apply.

Nothing here imports FastMCP. The tools layer translates ``SelectionError``
into a ``ToolError`` the model can read; keeping the data layer free of the
server makes every rule below testable with a plain function call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.core.exceptions import ValidationError as DjangoValidationError

from analytics.models import Request
from catalog.access import visible_feature_collections, visible_processing_options
from datasets.models import Dataset, DatasetResource
from features.models import FeatureCollection
from visualize.data import build_explore_data, build_request_data

from .formula import FormulaError, evaluate_formula, formula_columns, parse_formula


class SelectionError(ValueError):
    """The arguments do not describe a selection this caller can read.

    Always phrased for the model: say what was asked for, what is available,
    and which argument to change -- an assistant that gets "not found" with no
    alternatives will usually just give up or guess.
    """


@dataclass(frozen=True)
class Selection:
    """A resolved set of boundaries × data, plus what it has to be attributed to."""

    fc_ids: list[int]
    fc_names: list[str]
    po_ids: list[int] = field(default_factory=list)
    # None means "every resource"; a list narrows to particular years/files.
    resource_ids: list[int] | None = None
    request_id: str | None = None
    datasets: list[Dataset] = field(default_factory=list)
    feature_collections: list[FeatureCollection] = field(default_factory=list)

    @property
    def source(self) -> str:
        return "request" if self.request_id else "explore"


def _resolve_boundaries(user, boundaries: list[str]) -> list[FeatureCollection]:
    if not boundaries:
        raise SelectionError(
            "No boundaries given. Pass one or more feature collection names "
            "from search_boundaries, e.g. boundaries=['gB_v6_GHA_ADM2']."
        )
    found = list(
        visible_feature_collections(user).filter(name__in=boundaries).order_by("name")
    )
    missing = sorted(set(boundaries) - {fc.name for fc in found})
    if missing:
        # Deliberately does not distinguish "does not exist" from "you may not
        # see it": the distinction would leak the existence of private
        # collections, and the model's next move is the same either way.
        raise SelectionError(
            f"No boundary available named {', '.join(repr(m) for m in missing)}. "
            "Use search_boundaries to find the exact name."
        )
    return found


def _resolve_processing_options(user, dataset: str, extract_type: str | None):
    options = visible_processing_options(user).filter(dataset__name=dataset)
    if extract_type:
        options = options.filter(short_name=extract_type)
    resolved = list(options.select_related("dataset"))
    if not resolved:
        available = sorted(
            visible_processing_options(user)
            .filter(dataset__name=dataset)
            .values_list("short_name", flat=True)
        )
        if available:
            raise SelectionError(
                f"Dataset '{dataset}' has no extract type {extract_type!r}. "
                f"Available: {', '.join(available)}."
            )
        raise SelectionError(
            f"No dataset available named '{dataset}'. Use search_datasets to "
            "find the exact name, or list_available_data to see what is "
            "already processed for your boundaries."
        )
    return resolved


def _resolve_resources(
    dataset_ids: list[int], years: list[int] | None, resources: list[str] | None
) -> list[int] | None:
    """Resource ids for the requested years or resource names, or ``None``.

    ``None`` -- meaning every resource -- is not the same as ``[]``, which
    would select nothing; an empty result raises instead so the caller never
    silently gets a blank table for a year that does not exist.
    """
    if not years and not resources:
        return None

    qs = DatasetResource.objects.filter(dataset_id__in=dataset_ids)
    if resources:
        qs = qs.filter(name__in=resources)
    if years:
        qs = qs.filter(temporal__year__in=years)

    ids = list(qs.values_list("id", flat=True))
    if not ids:
        available = sorted(
            {
                t.year
                for t in DatasetResource.objects.filter(
                    dataset_id__in=dataset_ids, temporal__isnull=False
                ).values_list("temporal", flat=True)
            }
        )
        wanted = years or resources
        raise SelectionError(
            f"Nothing matches {wanted!r}. "
            + (
                f"Available years: {', '.join(str(y) for y in available)}."
                if available
                else "This dataset has no time dimension; omit years/resources."
            )
        )
    return ids


# A request id arrives as a string the model copied from somewhere, so a
# malformed one is routine, not exceptional. Django raises ValidationError
# (not ValueError) when a non-UUID reaches a UUIDField lookup, and that would
# escape as an opaque tool failure rather than something the model can fix.
_LOOKUP_ERRORS = (Request.DoesNotExist, DjangoValidationError, ValueError, TypeError)


def get_request_or_error(request_id: str, hint: str) -> Request:
    """Fetch a Request by id, turning any bad id into a readable error."""
    try:
        return Request.objects.get(id=request_id)
    except _LOOKUP_ERRORS:
        raise SelectionError(
            f"No request found with id '{request_id}'. {hint}"
        ) from None


def _resolve_request(request_id: str) -> Request:
    req = get_request_or_error(
        request_id, "Check the id, or use list_my_requests."
    )
    if req.status != 1:
        raise SelectionError(
            f"Request {request_id} is not finished yet (status: "
            f"{req.status}). Use get_request_status to follow it; its results "
            "become readable once it completes."
        )
    return req


def resolve_selection(
    user,
    *,
    boundaries: list[str] | None = None,
    dataset: str | None = None,
    extract_type: str | None = None,
    years: list[int] | None = None,
    resources: list[str] | None = None,
    request_id: str | None = None,
) -> Selection:
    """Resolve tool arguments into a Selection, or raise ``SelectionError``."""
    if request_id:
        if boundaries or dataset:
            raise SelectionError(
                "Give either request_id (a finished export) or "
                "boundaries + dataset (live pre-processed data), not both."
            )
        req = _resolve_request(request_id)
        fcs = list(req.feature_collections().order_by("group_level", "name"))
        names = [
            d.get("dataset_name")
            for d in (req.data or {}).get("datasets") or []
            if d.get("dataset_name")
        ]
        by_name = {d.name: d for d in Dataset.objects.filter(name__in=names)}
        return Selection(
            fc_ids=[fc.id for fc in fcs],
            fc_names=[fc.name for fc in fcs],
            request_id=str(req.id),
            datasets=[by_name[n] for n in dict.fromkeys(names) if n in by_name],
            feature_collections=fcs,
        )

    if not dataset:
        raise SelectionError(
            "No dataset given. Pass dataset= (see list_available_data for what "
            "is already processed for your boundaries), or request_id= to read "
            "a finished export."
        )

    fcs = _resolve_boundaries(user, boundaries or [])
    pos = _resolve_processing_options(user, dataset, extract_type)
    dataset_ids = sorted({po.dataset_id for po in pos})
    return Selection(
        fc_ids=[fc.id for fc in fcs],
        fc_names=[fc.name for fc in fcs],
        po_ids=[po.id for po in pos],
        resource_ids=_resolve_resources(dataset_ids, years, resources),
        datasets=[pos[0].dataset],
        feature_collections=fcs,
    )


def load_payload(selection: Selection) -> dict:
    """Build the value payload for a selection.

    Both branches go through ``visualize.data``, the same builder the web
    viz routes use, so a number here is the same number the app shows.
    """
    if selection.request_id:
        return build_request_data(Request.objects.get(id=selection.request_id))
    return build_explore_data(
        selection.fc_ids, selection.po_ids, selection.resource_ids
    )


def with_partial_flags(payload: dict) -> dict:
    """``{column: bool}`` -- is this column present for only some features?

    Mirrors the explore page's own partial-column badge. It matters because a
    partially processed column will happily render a map that looks complete
    while quietly omitting half the country, and the user has no way to tell
    from the numbers alone.
    """
    features = payload.get("features") or {}
    total = len(features)
    flags: dict[str, bool] = {}
    for col in payload.get("columns") or []:
        nulls = sum(1 for feat in features.values() if feat.get(col) is None)
        flags[col] = 0 < nulls < total
    return flags


def apply_formula(payload: dict, formula: str) -> str:
    """Evaluate a formula over every feature, adding it as a derived column.

    Mutates ``payload`` in place -- adding the column to ``columns`` and a
    value to each feature -- and returns the new column's name, which is
    prefixed with ``~`` exactly as the web app names a custom index, so the
    ``?formula=`` deep link reproduces it.
    """
    try:
        expr = parse_formula(formula)
    except FormulaError as exc:
        raise SelectionError(f"Could not parse formula {formula!r}: {exc}") from None

    known = set(payload.get("columns") or [])
    missing = [c for c in formula_columns(expr) if c not in known]
    if missing:
        raise SelectionError(
            f"Formula references unknown column(s): {', '.join(missing)}. "
            f"Available columns: {', '.join(sorted(known)) or '(none)'}."
        )

    name = f"~{formula}"
    for feat in (payload.get("features") or {}).values():
        feat[name] = evaluate_formula(expr, feat)
    payload["columns"] = [*(payload.get("columns") or []), name]
    payload.setdefault("col_dataset_titles", {})[name] = "Formula"
    payload.setdefault("col_descriptions", {})[name] = formula
    return name
