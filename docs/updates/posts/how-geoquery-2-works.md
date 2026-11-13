---
date: 2026-11-13 11:00:00
slug: how-geoquery-2-works
categories:
  - Development
description: "How GeoQuery 2.0 is built: a shared library of extracted results, coverage-aware datasets, documentation generated from the data itself, and open APIs."
---

# How GeoQuery 2.0 works

GeoQuery 2.0 was rebuilt around one idea: a result should only ever be computed once. Here's a look at how the new platform is put together, and why.

<!-- more -->

## One shared library of results

Every value GeoQuery returns comes from an *extract task*: one dataset, one time period, one area, one statistic. Tasks are shared across all requests: when two people ask for the same data for the same area, the second request reuses the first one's result.

GeoQuery has now computed more than 2.8 billion of these results. GeoQuery also computes results ahead of time in the background, so many requests now finish in under a minute.

## Datasets that know where they apply

Each dataset records the area it covers. For datasets that don't cover the whole world, GeoQuery checks every boundary against that coverage and offers the dataset only where it has data. Adding a boundary set or changing a dataset's coverage updates these checks automatically, without discarding any results already computed.

## Documentation generated from the data

The [dataset](../../data_documentation/datasets/index.md) and [boundary](../../data_documentation/boundaries/index.md) pages in these docs are generated every night from GeoQuery's own database, so each page always matches what you can request in the app, from time periods and licenses to which datasets cover which countries.

## Built in the open

GeoQuery 2.0 is built with Django and PostGIS on the server and SvelteKit in the browser, runs on Kubernetes, and its [source code](https://github.com/aiddata/geoquery) is public. Alongside the web app, a public [API](https://geoquery.aiddata.wm.edu/api/public/v1/docs/) and a [STAC](https://stacspec.org) catalog describe every dataset and boundary set in standard, machine-readable forms.

The [statistics page](https://geoquery.aiddata.wm.edu/stats) shows how the platform is doing right now: whether requests are flowing normally, how long they're taking, and what people are requesting most.
