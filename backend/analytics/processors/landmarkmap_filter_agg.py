import logging
import re
import sqlite3
from itertools import product

import geopandas as gpd


logger = logging.getLogger(__name__)

TABLE_NAME = "landmarkmap_ipcl"

# filter keys are interpolated directly into SQL as column identifiers (SQLite
# has no way to parameterize identifiers), so they're validated against this
# pattern before use - only filter *values* are escaped by _to_sql_literal
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(key: str) -> str:
    """Validate a filter key is safe to interpolate as a SQL column identifier."""
    if not isinstance(key, str) or not _IDENTIFIER_RE.match(key):
        raise ValueError(f"Unsafe or invalid filter key: {key!r}")
    return key


def _safe_number(value) -> float:
    """Validate a range bound is numeric before interpolating it into SQL."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Range filter bound must be numeric, got: {value!r}")
    return value


def _bbox_clause(dataset_path, feat):
    """Return an R-tree bounding-box SQL clause, or None if index unavailable."""
    try:
        with sqlite3.connect(str(dataset_path)) as conn:
            row = conn.execute(
                "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
                (TABLE_NAME,),
            ).fetchone()
        geom_col = row[0] if row else "geometry"
        rtree = f"rtree_{TABLE_NAME}_{geom_col}"
        minx, miny, maxx, maxy = feat.bounds
        return (
            f'rowid IN (SELECT id FROM "{rtree}" '
            f"WHERE minx <= {maxx} AND maxx >= {minx} "
            f"AND miny <= {maxy} AND maxy >= {miny})"
        )
    except Exception:
        # falls back to an unindexed full-table scan - log so a real bug here
        # (as opposed to "no rtree index exists") doesn't silently tank
        # performance on a ~330k row table with no visibility into why
        logger.warning(
            "landmarkmap bbox clause failed, falling back to full-table scan",
            exc_info=True,
        )
        return None


def _safe_label(value) -> str:
    """Convert a filter value to a safe column name segment."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(value)).strip("_")
    return s[:32] if len(s) > 32 else s


def _to_sql_literal(v) -> str:
    """Return a SQL literal for v, emitting 0/1 for Python booleans."""
    if isinstance(v, bool):
        return str(int(v))
    return "'" + str(v).replace("'", "''") + "'"


def _build_clauses(filters_agg: dict) -> list[str]:
    """Build SQL WHERE clauses for aggregate=True filters."""
    clauses = []
    for key, value in filters_agg.items():
        key = _safe_identifier(key)
        if value["type"] == "range":
            start, end = _safe_number(value["start"]), _safe_number(value["end"])
            clauses.append(f'"{key}" >= {start}')
            clauses.append(f'"{key}" <= {end}')
        elif value["type"] == "categorical":
            selected = value["selected"]
            if not selected:
                continue
            placeholders = ", ".join(_to_sql_literal(v) for v in selected)
            clauses.append(f'"{key}" IN ({placeholders})')
    return clauses


def landmarkmap_filter_and_agg(feat, dataset_path, name, **filters):
    """Filter LandmarkMap features by spatial and attribute criteria, then aggregate.

    Filters with aggregate=True are applied as a single pass and summed together.
    Filters with aggregate=False each produce one output column per selected value
    (or one column per combination when multiple non-aggregate filters are present).

    No outcome variable to aggregate. The result is simply the percentage of the feat that is covered by the filtered LandmarkMap features. The output is a list of tuples (column_name, value).
    """
    agg_filters = {}
    non_agg_filters = {}
    for key, value in filters.items():
        if not isinstance(value, dict):
            continue
        if value.get("aggregate", True):
            agg_filters[key] = value
        else:
            if value["type"] == "categorical":
                non_agg_filters[key] = value.get("selected", [])
            elif value["type"] == "range":
                # ranges aren't naturally splittable into discrete per-value
                # output columns the way categoricals are, so a non-aggregate
                # range filter is still applied as a single WHERE bound rather
                # than producing one column per value
                agg_filters[key] = value

    base_clauses = _build_clauses(agg_filters)
    if feat is not None:
        bbox = _bbox_clause(dataset_path, feat)
        if bbox:
            base_clauses = [bbox] + base_clauses

    if not non_agg_filters:
        sql = f"SELECT * FROM {TABLE_NAME}"
        if base_clauses:
            sql += " WHERE " + " AND ".join(base_clauses)
        gdf = gpd.read_file(dataset_path, sql=sql, use_arrow=True)
        if gdf.empty or feat is None:
            return [(name, 0)]
        # dissolve / union all geometries then check intersection
        intersection_area = gdf.geometry.union_all().intersection(feat).area
        percentage_intersection = (intersection_area / feat.area) if feat.area > 0 else 0
        return [(name, percentage_intersection)]

    keys = list(non_agg_filters.keys())
    value_lists = [non_agg_filters[k] for k in keys]
    results = []

    for combo in product(*value_lists):
        combo_clauses = list(base_clauses)
        label_parts = []
        for key, val in zip(keys, combo):
            combo_clauses.append(f'"{_safe_identifier(key)}" = {_to_sql_literal(val)}')
            label_parts.append(_safe_label(val))

        sql = f"SELECT * FROM {TABLE_NAME}"
        if combo_clauses:
            sql += " WHERE " + " AND ".join(combo_clauses)

        gdf = gpd.read_file(dataset_path, sql=sql, use_arrow=True)
        col_name = f"{name}_{'_'.join(label_parts)}"

        if gdf.empty or feat is None:
            results.append((col_name, 0))
            continue

        intersection_area = gdf.geometry.union_all().intersection(feat).area
        percentage_intersection = (intersection_area / feat.area) if feat.area > 0 else 0

        results.append((col_name, percentage_intersection))

    return results
