# Precise rasterstats processors

Date: 2026-10-30

## Goal

Add "precise" zonal statistics processors that use the AidData rasterstats
fork's latitude correction and percent-cover weighting, so datasets can offer
area-aware mean, sum and count alongside the existing `rasterstats_default_*`
options.

## Background

GeoQuery pins `aiddata/geoquery-python-rasterstats` at
`85f58864c5f78b4c4cd314e92a4e141c693d6dc0`. The fork's `zonal_stats` accepts:

- `latitude_correction` — weights each pixel row by its true area at that
  latitude. Affects **mean only**.
- `percent_cover_weighting` with `percent_cover_scale` — weights each pixel by
  the fraction of it covered by the geometry, estimated by rasterizing at
  `scale × scale` sub-pixel resolution. Affects **count, sum and mean**
  (count becomes a fractional pixel count). Not applied to min/max, to
  categorical counts, or to point geometries (the fork disables it for points).
- `limit` — maximum source pixels per tile; larger geometries are split into
  grid-aligned tiles and the per-tile stats are aggregated.

Percent cover allocates an upsampled grid of `window_pixels × scale²` cells, so
without `limit` a large boundary on a fine raster (e.g. a country on 30 m
Hansen) cannot fit in memory.

## Design

### Processors

In `backend/analytics/processors/zonal_stats_rasterstats.py`:

- `_PRECISE_DEFAULTS`: per-stat default kwargs.
  - all precise stats: `percent_cover_weighting=True`,
    `percent_cover_scale=10`, `limit=1_000_000`
  - `mean` additionally: `latitude_correction=True`
- `_precise_kwargs(stat, kwargs)`: merges, lowest precedence first,
  `_rasterstats_kwargs` defaults (`all_touched=True`, `nodata=None`), then
  `_PRECISE_DEFAULTS[stat]`, then the caller's kwargs (processing option and
  task kwargs). Caller kwargs always win, so a dataset can override `limit` or
  `percent_cover_scale`.
- Public single-feature functions, each delegating to the existing
  `_rasterstats_default` with the merged kwargs and returning the same
  `[(name, value)]` shape:
  - `rasterstats_precise_mean`
  - `rasterstats_precise_sum`
  - `rasterstats_precise_count`
- Batch forms via `_batch_precise(stat)`, built on the existing `_batched`
  helper exactly like `_batch_default`, added to `BATCH` under the same keys.

In `backend/analytics/processors/__init__.py`: import and register the three
functions in `REGISTRY`. `BATCH_REGISTRY` picks up the batch forms from
`BATCH`. Registry keys are persisted in `ProcessingOption.function` and ingest
JSON, so these names are permanent once used.

### Behavior notes

- `rasterstats_precise_count` returns a float; processing options using it
  should declare `result_type: "float"`.
- Point geometries: percent cover is disabled by the fork, so precise results
  equal default results except for latitude correction on mean.
- Latitude correction assumes rasters in EPSG:4326 (all GeoQuery rasters).
  Documented in the function docstrings.
- With the default `limit`, each upsampled tile is 1M source pixels × 100
  sub-pixels = 100M cells; the fork rasterizes to uint8 then copies to bool, so
  peak memory is roughly 200 MB per tile. Larger features are split and
  aggregated by the fork.
- The fork emits a UserWarning when `percent_cover_scale` is missing or
  `all_touched` is off; the defaults supply both, so normal runs are
  warning-free.

## Testing

GeoQuery tests (`docker compose exec backend uv run python manage.py test`):

- `analytics/tests/test_batch_processors.py` — the existing registry-coverage
  and batch-equals-single tests cover the new processors automatically; confirm
  they pass with them registered.
- New `analytics/tests/test_precise_processors.py`:
  - a pixel half covered by the geometry contributes 0.5 to precise count and
    half its value to precise sum;
  - precise mean on a high-latitude raster differs from default mean in the
    direction latitude weighting predicts (rows nearer the equator weigh more);
  - with a small `limit` override forcing splits, precise mean/sum/count for a
    large feature match the unsplit results within float tolerance;
  - caller kwargs override defaults (`limit`, `percent_cover_scale`).

## Out of scope

- Adding precise processing options to datasets (geo-datasets ingest JSON) —
  follow-up work.
- Precise min/max/categorical — the corrections do not change them.
- Changes to the rasterstats fork.
