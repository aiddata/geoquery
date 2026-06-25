import sqlite3
import geopandas as gpd


TABLE_NAME = "gcdf_v301_dynamic"


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
        return None


def gcdf_v301_dynamic_filter_and_agg(feat, dataset_path, name, **filters):
    """Filter GCDF v3.0.1 dynamic dataset by spatial and attribute criteria, then aggregate.

    Round results to integers.
    """
    agg_field = "Commitment Value"

    clauses = []

    # Bounding-box pre-filter via GPKG R-tree index (plain SQLite, no SpatiaLite)
    if feat is not None:
        bbox = _bbox_clause(dataset_path, feat)
        if bbox:
            clauses.append(bbox)

    for key, value in filters.items():
        if not isinstance(value, dict):
            continue
        if value["type"] == "range":
            start, end = value["start"], value["end"]
            clauses.append(f'"{key}" >= {start}')
            clauses.append(f'"{key}" <= {end}')
        elif value["type"] == "categorical":
            selected = value["selected"]
            if not selected:
                continue
            placeholders = ", ".join(
                "'" + str(v).replace("'", "''") + "'" for v in selected
            )
            clauses.append(f'"{key}" IN ({placeholders})')

    sql_query = f"SELECT * FROM {TABLE_NAME}"
    if clauses:
        sql_query += " WHERE " + " AND ".join(clauses)

    gdf = gpd.read_file(dataset_path, sql=sql_query, use_arrow=True)

    if gdf.empty or feat is None:
        return [(name, 0)]

    # Precise shapely intersection with area-proportional aggregation
    intersection_area = gdf.geometry.intersection(feat).area
    proportion = (intersection_area / gdf.geometry.area).fillna(0)

    weighted_sum = (gdf[agg_field] * proportion).sum()
    return [(name, int(weighted_sum))]
