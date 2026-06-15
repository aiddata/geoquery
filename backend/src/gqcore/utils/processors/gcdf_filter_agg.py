import geopandas as gpd

def gcdf_v301_dynamic_filter_and_agg(feat, dataset, **filters):

    agg_field = "Commitment Value"

    dataset_gdf = gpd.read_file(dataset)

    filtered_gdf = dataset_gdf.copy()

    for key, value in filters.items():
        if key in filtered_gdf.columns:
            if key["type"] == "range":
                filtered_gdf = filtered_gdf[
                    (filtered_gdf[key] >= value[0]) & (filtered_gdf[key] <= value[1])
                ]
            elif key["type"] == "categorical":
                filtered_gdf = filtered_gdf[filtered_gdf[key].isin(value)]
            else:
                raise ValueError(f"Unsupported filter type for key: {key}")

    geo_filtered_gdf = filtered_gdf[filtered_gdf.geometry.intersects(feat)]

    sum_value = geo_filtered_gdf[agg_field].sum()

    output = sum_value if sum_value is not None else 0

    return output
