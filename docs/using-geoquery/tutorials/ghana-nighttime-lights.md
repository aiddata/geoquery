---
description: "A worked example: extract nighttime lights for every district in Ghana with GeoQuery, then compare two years and map the result."
---

# Nighttime lights for Ghana's districts

Nighttime lights, measured by satellite, are a common proxy for economic activity and electrification. This tutorial gets the average night light intensity for each of Ghana's 260 districts in 2022 and 2023, then compares the two years and maps the change.

It takes about five minutes, plus the time your request takes to process.

## 1. Select Ghana's districts

1. Open [GeoQuery](https://geoquery.aiddata.wm.edu).
2. Type `Ghana ADM2` into the boundary search and choose **geoBoundaries v6 - Ghana ADM2 (Districts)**. The map shows Ghana's districts, and the panel says 260 features are selected: one per district.
3. Click **Find Data**.

## 2. Choose the dataset and its options

1. Search the dataset list for `VIIRS` and click **Annual VIIRS Nighttime Lights v2.2 - Average Value**.
2. Under **Measure**, tick **Average light intensity**. This is the mean of the satellite's readings across each district. The ⓘ icon beside each measure says what it is.
3. Under **Split results by**, tick **2022** and **2023** in **Time Periods**. Each period you tick becomes its own column.

The dataset is added to your request as soon as you've chosen: the line under **Select Dataset Options** says "Dataset added. 2 columns based on Average light intensity across 2 years."

## 3. Review and submit

1. Click **Continue to Review**. The Review page shows the 260 districts and the dataset, with 2 columns for each district.
2. In the panel, give your request a name, such as `Ghana district lights 2022-2023`, and enter your email address (or sign in).
3. Click **Submit Request**. Your request's page shows its progress, and we'll email you when it's ready.

## 4. Read the results

Download and unzip your results. `<request id>_results.csv` has one row per district, with columns including:

| Column | What it holds |
|--------|---------------|
| `boundary.shapeName` | The district's name |
| `viirs_ntl_annual_v22_avg_masked_2022.mean` | Average night light intensity in 2022 |
| `viirs_ntl_annual_v22_avg_masked_2023.mean` | Average night light intensity in 2023 |

To see which districts got brighter, add a column that subtracts the 2022 value from the 2023 value, in Excel, R or Stata. The documentation file in your download describes the dataset's units and how to cite it. See [Using your results](../results.md) for the other columns.

## 5. Map the change

1. In QGIS, add `request_features.gpkg` and the results CSV as layers.
2. Open the GeoPackage layer's properties, and add a join to the CSV on `feature_collection` and `geom_id`.
3. Style the layer by the 2023 value, or by your change column, to map it.

## Going further

- **Add more years or measures** with **Duplicate request** › **Open in a new tab** on your request's page: it loads this request for you to change and submit again.
- **Share your results** with **Copy results link** on your request's page, or **share your setup** with **Duplicate request** › **Copy link**, so a colleague can start the same request.
- **Compare levels**: add **Ghana ADM1** to see regions alongside districts. See [Selecting multiple boundary sets](../multiple-boundaries.md) for how the results are laid out.
