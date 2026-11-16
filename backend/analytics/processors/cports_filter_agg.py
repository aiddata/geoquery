import sqlite3
import geopandas as gpd


TABLE_NAME = "cports_v20_dynamic"


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


# Outcomes this processor can add up, by the key the dataset's "outcomes"
# metadata offers. One for now; another column here is another measure.
OUTCOMES = {"value": "value"}


def cports_v20_dynamic_filter_and_agg(feat, dataset_path, name, outcome="value", **filters):
    """Filter CPORTS v2.0 dynamic dataset by spatial and attribute criteria, then aggregate.

    Args:
        outcome: Key of the measure to add up (see OUTCOMES); "value" is the
            commitment value.

    Round results to integers.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown CPORTS outcome {outcome!r}")
    agg_field = OUTCOMES[outcome]

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

    # check if feature contains the geometry of the gdf, if not, return 0
    gdf["within_feat"] = gdf.geometry.within(feat)

    gdf["final_value"] = gdf.apply(
        lambda row: row[agg_field] if row["within_feat"] else 0, axis=1
    )

    total = gdf["final_value"].sum()

    return [(name, int(total))]
