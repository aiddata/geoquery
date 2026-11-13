# Getting Started

## Submitting a request

1. **Select boundaries.** Open the GeoQuery application and search for a country or boundary set, or pick one from the featured list. To narrow a single boundary set to a few areas, click them on the map. Then click **Find Data**.
2. **Choose datasets.** Browse the datasets available for your boundaries. For each one, choose the statistics and time periods you want, then click **Add to Request**. You can add as many datasets as you like, and the same dataset more than once with different options.
3. **Review.** Click **Review Request** to check your boundaries and datasets.
4. **Submit.** In the Review & Submit panel, give your request a name and enter your email address (if you're signed in, your account's email is used), then click **Submit Request**.
5. **Download.** We'll email you a link when your results are ready. See [Using your results](results.md) for what's included.

Signed in with GitHub, you can also find all your requests in one place. See [Accounts and request history](accounts.md).

## Boundary files

GeoQuery offers administrative boundaries for countries around the world, as well as other boundary sets. See the [Boundaries](../data_documentation/boundaries/index.md) documentation for the full list.

**Coming soon:** you'll also be able to use your own boundaries, by uploading a GeoJSON file (`.geojson` or `.json`, up to 50 MB) from the **Custom** tab on the boundary selection page.

## Multiple boundaries

You can select as many boundary sets as you like in a single request, across countries and levels (for example, Ghana ADM1, Ghana ADM2 and Tanzania ADM1). Selecting individual features, such as a few districts, is only available within one boundary set at a time. Each boundary set is kept separate: every area gets its own row in your results, labelled with its boundary set, so if your sets overlap, for example a country's ADM1 and ADM2 levels, each area is still summarized on its own rather than combined or intersected. Previously processed data is cached, so repeat selections are returned much faster.

## What you'll receive

Each completed request is a zip file containing:

| File | Description |
|------|-------------|
| `<request id>_results.csv` | Your extracted values, one row per area, for Excel, Stata, SPSS, R, or similar tools |
| `request_features.gpkg` | Your areas' boundaries as a GeoPackage, for GIS software |
| `<request id>_documentation.html` | Metadata: each dataset's description, source, license and citation |
| `request_details.json` | The full details of your request, for programmatic use |
| `GeoQuery_Goodman2019.pdf` | The paper describing GeoQuery's methods, which should be cited when you use GeoQuery data |

See [Using your results](results.md) for how to read the CSV and join it to the boundaries.

## Turnaround time

Many requests return almost immediately thanks to preprocessing and caching. Requests that require new processing, particularly those covering large areas or many locations, may take up to several hours.

## Resources and tutorials

Tutorials and worked examples are listed under [Tutorials](tutorials/index.md). For videos and examples of research using GeoQuery, see [aiddata.org/geoquery](https://www.aiddata.org/geoquery).
