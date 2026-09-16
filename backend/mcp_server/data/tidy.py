"""The long (tidy) shape of a selection: one row per feature per year.

GeoQuery's payloads are wide -- one column per resource, so twenty-five years
of a dataset is twenty-five columns whose year lives only in the column name.
That is the right shape for a map and the wrong one for the question people
actually ask most often, "how did this change over time here", which in wide
form means asking for twenty-five columns and pivoting them by hand.

Two things are needed to turn the wide payload sideways: the year each column
belongs to, which the payload does not carry, and the first-to-last change per
series, which is the next question after the series itself.
"""

from __future__ import annotations

import re
from collections import defaultdict

_YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|2[01]\d{2})(?!\d)")


def _year_from_text(*candidates: str | None) -> int | None:
    """Last four-digit year appearing in any of these strings.

    The fallback for a column whose resource row has no ``temporal``. Last
    rather than first because a resource is named like ``esa_lc_2015`` far
    more often than it is named like ``2015_esa_lc``, and a dataset name can
    itself contain a year (``ghsl_2023_release``) ahead of the real one.
    """
    for text in candidates:
        if not text:
            continue
        found = _YEAR_RE.findall(text)
        if found:
            return int(found[-1])
    return None


def column_years(selection, payload: dict, columns: list[str]) -> dict[str, int | None]:
    """``{column: year}``, from the resource's own ``temporal`` where possible.

    A column is ``<resource name>.<extract name>``, so the resource rows hold
    the authoritative date. They are looked up in one query, narrowed to the
    selection's datasets so that two datasets sharing a resource name cannot
    date each other's columns.
    """
    from datasets.models import DatasetResource

    resource_names = {col.rsplit(".", 1)[0] for col in columns}
    qs = DatasetResource.objects.filter(name__in=resource_names)
    dataset_ids = [d.id for d in selection.datasets]
    if dataset_ids:
        qs = qs.filter(dataset_id__in=dataset_ids)
    dated = {
        name: temporal.year
        for name, temporal in qs.values_list("name", "temporal")
        if temporal
    }

    temporal_labels = payload.get("col_temporal") or {}
    return {
        col: dated.get(col.rsplit(".", 1)[0])
        or _year_from_text(temporal_labels.get(col), col.rsplit(".", 1)[0])
        for col in columns
    }


def series_name(column: str, dataset_titles: dict) -> str:
    """What a column is a yearly instance *of*.

    ``esa_lc_2015.mean`` and ``esa_lc_2020.mean`` are two points in one series;
    ``esa_lc_2015.count`` is a different one. The extract name distinguishes
    them, and the dataset title keeps two datasets' ``mean`` apart.
    """
    stem = column.rsplit(".", 1)[-1]
    title = dataset_titles.get(column)
    return f"{title} {stem}".strip() if title else stem


def long_rows(page, columns, years, dataset_titles) -> list[dict]:
    """One row per (feature, column), carrying the year as data not as a name."""
    return [
        {
            "feature_id": int(geom_id),
            "name": record.get("name"),
            "fc": record.get("fc"),
            "column": col,
            "series": series_name(col, dataset_titles),
            "year": years.get(col),
            "value": record.get(col),
        }
        for geom_id, record in page
        for col in columns
    ]


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def series_change(page, columns, years, dataset_titles) -> list[dict]:
    """First-to-last change per feature per series, absolute and percent.

    Undated columns are left out entirely rather than ordered arbitrarily: a
    "change" computed between two points whose order is a guess is worse than
    no change column at all. So is one computed from a single point, so a
    series needs at least two.
    """
    points: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for geom_id, record in page:
        for col in columns:
            year = years.get(col)
            value = record.get(col)
            if year is None or not _numeric(value):
                continue
            key = (int(geom_id), record.get("name"), series_name(col, dataset_titles))
            points[key].append((year, float(value)))

    changes = []
    for (feature_id, name, series), series_points in points.items():
        if len(series_points) < 2:
            continue
        series_points.sort()
        (first_year, first), (last_year, last) = series_points[0], series_points[-1]
        changes.append(
            {
                "feature_id": feature_id,
                "name": name,
                "series": series,
                "first_year": first_year,
                "first_value": first,
                "last_year": last_year,
                "last_value": last,
                "absolute_change": last - first,
                # Undefined rather than infinite when the series starts at
                # zero; a model that sees a number here will quote it.
                "percent_change": (
                    round((last - first) / first * 100, 4) if first else None
                ),
                "points": len(series_points),
            }
        )
    return sorted(changes, key=lambda c: (c["name"] or "", c["series"]))
