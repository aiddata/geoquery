---
description: "How to make a GeoQuery request: select boundaries, choose datasets and their options, review, submit, and download your results."
---

# Getting Started

GeoQuery takes you through three steps, shown in the panel on the left of the [GeoQuery application](https://geoquery.aiddata.wm.edu): **1. Select Boundaries**, **2. Customize Datasets** and **3. Review & Submit**. Your choices are kept as you move between them, and through a refresh of the page.

## Submitting a request

1. **Select boundaries.** Open [GeoQuery](https://geoquery.aiddata.wm.edu) and search for a country or boundary set, or pick one from **Featured Boundaries**. A **feature** is one area in a boundary set, such as a single district in Ghana ADM2; your results have one row per feature.
    - **Narrow to a few features** by clicking them on the map. This works when one boundary set is selected.
    - **Pick many boundary sets at once** with **Bulk select**, under the search box. It groups every boundary set by level, from ADM0 (countries) down, so you can tick a whole level at once.
    - **Use a preset** by typing a region or group into the search, such as "Africa ADM1" or "LMIC". See [Boundary presets](../data_documentation/boundary-presets.md).

    Click **Find Data**, or **2. Customize Datasets** in the panel, to move on.

2. **Choose datasets.** Browse the datasets available for your boundaries; the search box also matches categories, such as "climate" or "economic". For each dataset, choose a **Measure** (such as mean or maximum) and what to **Split results by**, such as time periods. A dataset joins your request as soon as these are chosen, and the line under **Select Dataset Options** says so: "Dataset added", or which options are still missing. A required option with nothing chosen is outlined in red. There's nothing to click to add it, and **Reset** takes it out again. See [Dataset coverage](#dataset-coverage) if a dataset you expected isn't listed.

    Datasets of events or locations, such as conflict events, can be in your request more than once, each **selection** with its own options and its own columns. Each selection has a card above the options, with a check mark when it's in your request. **New selection** keeps the current one and starts another. These datasets can also narrow which records count, under **Custom filters**.

3. **Review.** Click **Continue to Review**, or **3. Review & Submit** in the panel. The Review page shows your boundaries, each dataset and its options, and how many rows your results will have. Use **Modify Boundary Sets**, **Add Another Dataset**, or **Edit options** on any dataset to make changes.

4. **Submit.** In the panel, give your request a name and enter your email address (if you're signed in, your account's email is used), then click **Submit Request**.

5. **Download.** We'll email you a link when your results are ready. See [Using your results](results.md) for what's in the download and how to read it.

Signed in with GitHub, you can also find all your requests in one place. See [Accounts and request history](accounts.md).

## Dataset coverage

GeoQuery only lists datasets that have data for the boundaries you've selected. A dataset that covers only some regions, such as one for Africa, doesn't appear when your boundaries are elsewhere. Each dataset's page in the [data documentation](../data_documentation/datasets/index.md) describes where and when it has data.

With several boundary sets selected, a dataset that covers some of them but not all has a partly filled circle beside it. Hover over it to see how many of your boundary sets it covers. You can also sort the list by coverage.

## Sharing a request

**Copy share link**, at the bottom of the panel on every step, copies a short link to the request you're building. Anyone who opens the link gets their own copy of your boundaries, datasets and options, opened on the Review page, and can change it before submitting.

A share link is a snapshot. If you change your request after copying its link, the button changes to **Copy updated link**; the earlier link still opens the request as it was. Requests that use an uploaded boundary file can't be shared this way.

Once you've submitted a request, its page has two more ways to share it:

- **Copy results link** copies the address of the request's page, where anyone with the link can see its progress and download its results.
- **Duplicate request** › **Copy link** copies a share link to the request's boundaries, datasets and options, for someone to start their own request from.

## Starting from a past request

To build on an earlier request, open its page and choose **Duplicate request** › **Open in a new tab**. Its boundaries, datasets and options are loaded into a new request in a new tab, opened on the Review page, for you to change and submit. A request you were building in the first tab isn't touched. If anything in the earlier request is no longer available, GeoQuery tells you what was left out.

## Boundary files

GeoQuery offers administrative boundaries for countries around the world, as well as other boundary sets. See the [Boundaries](../data_documentation/boundaries/index.md) documentation for the full list, and [Selecting multiple boundary sets](multiple-boundaries.md) for how a request with several sets is laid out.

**Coming soon:** you'll also be able to use your own boundaries, by uploading a GeoJSON file (`.geojson` or `.json`, up to 50 MB) with the **Custom upload** button above the boundary search, or by dragging the file onto the page.

## Next steps

- [Using your results](results.md): what's in your download and how to read it.
- [FAQ](../faq.md): turnaround times, limits, and other common questions.
- [Tutorials](tutorials/index.md): worked examples. For videos and research using GeoQuery, see [aiddata.org/geoquery](https://www.aiddata.org/geoquery).
