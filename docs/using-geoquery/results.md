---
description: "What's in a GeoQuery results download, how the results CSV is laid out, and how to join it to the boundaries in GIS software."
---

# Using your results

When your request is ready, we email you a link to download a zip file. This page explains what's in it and how to work with it.

## What's in the download

| File | What it's for |
|------|---------------|
| `<request id>_results.csv` | Your extracted values: one row per area |
| `request_features.gpkg` | The boundaries of those areas, as a GeoPackage for QGIS, ArcGIS, R, Python and other GIS tools |
| `<request id>_documentation.html` | Metadata for each dataset in your request: description, source, license and citation |
| `request_details.json` | The full details of your request, for scripts and record keeping |
| `GeoQuery_Goodman2019.pdf` | The paper describing GeoQuery's methods |

## Reading the results CSV

Each row is one area from your request. If you selected several boundary sets, each set's areas are listed separately, so an area that appears in two sets appears in two rows.

The columns are:

- **`feature_collection`**: the boundary set the area belongs to, for example `gB_57dcd43_GHA_ADM1`.
- **`geom_id`**: GeoQuery's ID for the area's boundary. Together with `feature_collection`, it identifies the row and links it to the boundary in `request_features.gpkg`.
- **`boundary.…`**: the attributes the boundary's source publishes for each area, such as its name and code. geoBoundaries areas, for example, have `boundary.shapeName`, `boundary.shapeISO`, `boundary.shapeID`, `boundary.shapeType` and `boundary.shapeGroup`. Other boundary sets have their own fields.
- **One column per value you requested**, named `<dataset and period>.<statistic>`. For example, `map_pf_incidence_rate_202608_2001.mean` is the mean of the Malaria Atlas Project's incidence rate for 2001. A request for several periods or statistics adds one column for each. Categorical datasets, such as land cover, have one column for each category.

An empty cell means the dataset has no data for that area and period, for example because the area lies outside the dataset's coverage or the source has no values there. It is not a zero.

The documentation file describes each dataset in your request, including its units and how to cite it.

## Mapping your results

To map your results, join the CSV to `request_features.gpkg` on both `feature_collection` and `geom_id`. In QGIS, for example, add both files as layers, then open the GeoPackage layer's properties and add a join on those fields.

## Citing your results

Please cite GeoQuery and each dataset you use. The citations are in the documentation file, and [Citing GeoQuery](../citing.md) explains what to include.
