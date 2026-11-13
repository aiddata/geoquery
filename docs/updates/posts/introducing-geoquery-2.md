---
date: 2026-11-13 12:00:00
slug: introducing-geoquery-2
categories:
  - Announcements
description: "GeoQuery 2.0 is a ground-up rebuild of AidData's free geospatial data extraction tool, with more data, faster results and new ways to work with GeoQuery."
---

# Introducing GeoQuery 2.0

GeoQuery has helped researchers turn satellite and other spatial data into simple tables since 2014, with nearly 49,000 requests made on earlier versions. GeoQuery 2.0 is a ground-up rebuild of the platform: the same idea, select your areas and datasets and get back a file with one row per area, on a new foundation built to grow.

<!-- more -->

## What's new

- **More boundaries.** Administrative boundaries from [geoBoundaries](https://www.geoboundaries.org) for 232 countries and territories, from national borders down to the finest levels each country publishes, plus other boundary sets such as city extents. There are 719 boundary sets in all.
- **A broader data library.** 63 datasets spanning population, economic activity, climate, the environment, health, conflict and natural resources, each with its own [documentation page](../../data_documentation/datasets/index.md) describing its source, coverage and citation.
- **Faster results.** GeoQuery 2.0 computes each result once and reuses it for everyone who asks for it, so a request for data that has already been extracted comes back in seconds rather than hours.
- **More in a single request.** Combine boundary sets from several countries or levels in one request, and choose exactly which areas, statistics and time periods you need.
- **Your request history.** Sign in to see past requests in one place, including those made on earlier versions of GeoQuery.
- **Programmatic access.** A public [API](https://geoquery.aiddata.wm.edu/api/public/v1/docs/) and a [STAC](https://stacspec.org) catalog let you search GeoQuery's datasets and boundaries from your own code and tools.

Uploading your own boundaries and visualizing results on a map are in testing now, and we'll share more about them here when they're ready.

## Still free, still open

GeoQuery remains free to use, and its [source code](https://github.com/aiddata/geoquery) is open. If you use it in your work, see [Citing GeoQuery](../../citing.md).

We'd love to hear how you're using GeoQuery 2.0, and what you'd like to see next. Write to us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu).
