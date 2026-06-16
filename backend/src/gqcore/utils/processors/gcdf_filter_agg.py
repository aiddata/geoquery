import geopandas as gpd


def gcdf_v301_dynamic_filter_and_agg(feat, dataset_path, name, **filters):
    agg_field = "Commitment Value"

    # Build attribute-only WHERE clause for SQL pushdown.
    # Empty categoricals mean no rows can match — short-circuit immediately.
    clauses = []
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
                continue  # No values selected means no filter needed
            placeholders = ", ".join(f"'{v}'" for v in selected)
            clauses.append(f'"{key}" IN ({placeholders})')

    sql_query = "SELECT * FROM gcdf_v301_dynamic"
    if clauses:
        sql_query += " WHERE " + " AND ".join(clauses)

    gdf = gpd.read_file(dataset_path, sql=sql_query, use_arrow=True)

    if gdf.empty or feat is None:
        return [(name, 0)]

    # Weight each row's value by the fraction of its area covered by feat.
    # Rows that don't intersect get proportion=0; no need for a separate filter.
    intersection_area = gdf.geometry.intersection(feat).area
    proportion = (intersection_area / gdf.geometry.area).fillna(0.0)

    weighted_sum = (gdf[agg_field] * proportion).sum()
    return [(name, int(round(weighted_sum)))]
