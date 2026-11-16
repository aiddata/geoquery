---
description: "How GeoQuery handles a request with more than one boundary set: each set is kept separate, every area gets its own row, and overlapping areas are not combined or intersected."
---

# Selecting multiple boundary sets

You can select as many boundary sets as you like in one request, across countries and levels. For example, you could select Ghana ADM1, Ghana ADM2 and Tanzania ADM1 together. When you do, the boundary page shows this note:

> **Each boundary set is kept separate.** Every area gets its own row in your results, labelled with its boundary set. Areas that overlap are included once in each set, not combined or intersected.

This page explains what that means for your results.

## Every area gets its own row

GeoQuery summarizes each area in each boundary set on its own. Your results CSV has one row per area per set, and the `feature_collection` column says which set each row comes from.

For example, Ghana ADM1 has 16 regions and Ghana ADM2 has 260 districts, so selecting both gives you 276 rows. Before you submit, the Review page shows how many rows your results will have.

## Overlapping areas are not combined

Boundary sets often overlap. A country's ADM1 regions cover the same land as its ADM2 districts, and two providers may draw the same country differently. GeoQuery doesn't merge, split or intersect overlapping areas:

- **Each area keeps its own boundary.** A region's values cover the whole region. The values for a district inside it cover just that district.
- **An area in two sets appears twice**, once in each set's rows, labelled with that set.
- **Nothing is added up across sets.** There's no row for "the part of a district inside a region", and no total across sets.

## Working with the results

- **Don't add up values across sets.** Where sets overlap, the same land is counted in each of them. To get totals for one set, filter or group the rows by `feature_collection` first.
- **Keep one set per analysis**, or compare sets side by side. For example, you can check that districts add up to their region for a count-based dataset.
- **For combined or intersected areas, work in GIS software.** `request_features.gpkg` in your download has every area's boundary, labelled with its set. You can overlay or intersect them there, and join the results by `feature_collection` and `geom_id`. See [Using your results](results.md) for how the files fit together.

## Selecting individual areas

Clicking areas on the map to narrow your selection only works when one boundary set is selected. With several sets selected, each set is included in full.
