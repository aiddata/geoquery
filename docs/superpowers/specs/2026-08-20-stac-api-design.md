# STAC API (discovery-only Phase 1)

**Status:** Approved, not yet implemented
**Date:** 2026-08-20

## Context

`public_api` (`backend/public_api/`, mounted at `/api/public/v1/`) shipped read-only GeoQuery-native JSON endpoints for datasets and boundaries. Its design spec flagged a forward-looking pattern for a STAC (SpatioTemporal Asset Catalog) layer: `Dataset` already holds STAC-relevant metadata (`temporal_start`/`temporal_end`, `spatial_extent`, tags), and `DatasetResource` — a per-file row under each Dataset — carries its own `temporal` value and `spatial_extent`, closely matching STAC's Collection/Item split.

**Goal:** build that STAC layer as a discovery surface — a standard, tool-compatible way for external users (STAC Browser, `pystac-client`, QGIS's STAC plugin) to search and browse what data GeoQuery has, by extent/time/collection. This is explicitly *not* about serving the underlying files: `DatasetResource.path` is an internal filesystem path used by the extraction pipeline, with no public download mechanism today (the only existing public downloads are zipped extraction *request results*, unrelated to raw source data).

Boundaries (`FeatureCollection`, exposed in `public_api` as `/boundaries/`) are in scope alongside datasets — they're the same shape of discoverable geospatial metadata (`title`, `tags`, `citation`, `source_name`/`url`, `temporal_start`/`end`, `spatial_extent`), just without a `DatasetResource`-equivalent sub-unit.

## Architecture

A new Django app, `stac_api/`, mounted at `/api/stac/v1/` in `geoquery/urls.py`. Mirrors `public_api`'s structure (`serializers.py`, `views.py`, `urls.py`, `base.py`) and its core design decision: own serializers translating the *same* `Dataset`/`DatasetResource` querysets `public_api` already uses (`active=True, public=True`), rather than a parallel data-access path or duplicated model.

No auth seam. Unlike `public_api`, `stac_api` has no `PublicApiKeyAuthentication`/`AllowAny`-during-beta stub — STAC catalogs are conventionally fully public with no key gating, and this layer never serves data, only metadata about it. Views get DRF's default `AllowAny` and standard IP-based throttling, no per-view auth/permission classes to maintain.

`drf-spectacular` scoped schema at `/api/stac/v1/docs/` and `/api/stac/v1/schema/`, same pattern as `public_api`'s scoped schema view.

**CORS.** Browser-based STAC clients (e.g. STAC Browser, a client-side SPA hosted on its own origin) fetch a catalog cross-origin, unlike CLI/server clients (`pystac-client`, crawlers), which aren't subject to CORS at all. The app-wide `django-cors-headers` config (`CORS_ALLOWED_ORIGINS` in `geoquery/settings.py`) is scoped to the Vite dev origin for the internal, cookie-authenticated frontend — not something to widen globally just for this. Instead, `stac_api`'s own base view mixin sets `Access-Control-Allow-Origin: *` unconditionally on every response, independent of the shared `corsheaders` app. Safe specifically because `stac_api` has no auth/credentials to protect (wildcard-origin + credentialed-request is what browsers disallow; there's nothing credentialed here).

## Endpoint scope (v1)

Targets OGC API - Features "Core" conformance plus the STAC Item Search extension:

- `GET /api/stac/v1/` — landing page (`type: "Catalog"`; links to self, conformance, collections, search, docs)
- `GET /api/stac/v1/conformance/` — conformance class list
- `GET /api/stac/v1/collections/` — all active+public Datasets *and* FeatureCollections, merged into one Collection list
- `GET /api/stac/v1/collections/{name}/` — single Collection (dataset or boundary set)
- `GET /api/stac/v1/collections/{name}/items/` — Items under that Collection (DatasetResources for a dataset; always exactly one synthetic Item for a boundary set), as a paginated ItemCollection
- `GET /api/stac/v1/collections/{name}/items/{item_id}/` — single Item
- `GET`/`POST /api/stac/v1/search/` — cross-collection: `bbox`, `datetime`, `collections[]`, `limit`

`{name}` reuses `Dataset.name`/`FeatureCollection.name`, the same identifiers `public_api` exposes as `/datasets/{name}/` and `/boundaries/{name}/` — keeps a dataset or boundary set's STAC identity aligned with its public-API identity for anyone cross-referencing the two surfaces.

**Collection id collision risk:** `Dataset.name` and `FeatureCollection.name` are each unique within their own table, but nothing enforces uniqueness *across* the two tables, and merging both into one `/collections/` namespace requires exactly that. No collision exists in current data (verified: 8 datasets, 8 feature collections, zero name overlap), so this ships as-is rather than adding an id prefix that would break the identity-alignment goal above. A CI test (see Testing) asserts the two name sets stay disjoint, so a future collision is caught at test time rather than surfacing as a silent 404/wrong-object bug in production.

## Data mapping

**Collection ← Dataset** (`active=True, public=True`):

| STAC field | Source |
|---|---|
| `id` / `title` | `name` / `title` |
| `description` | `description` |
| `keywords` | `tags` |
| `providers` | `[{name: source_name, url: source_url}]` when present |
| `license` | static `"See source"` — points consumers at the dataset's `source_name`/`source_url`/`citation` fields, since `Dataset` carries no license/SPDX metadata today |
| `extent.spatial` | bbox from `spatial_extent` |
| `extent.temporal` | `[temporal_start, temporal_end]`, open-ended (`null`) on either side if unset |

**Item ← DatasetResource**:

| STAC field | Source |
|---|---|
| `id` | `resource.name` |
| `collection` | `dataset.name` |
| `geometry` / `bbox` | `resource.spatial_extent`, falling back to the parent Dataset's `spatial_extent` when the resource has none |
| `datetime` | `resource.temporal`, falling back to `dataset.temporal_start` when unset |
| `assets` | `{}` — no downloadable asset (see below) |
| `links` | includes one `rel: "via"` entry pointing at the GeoQuery dataset page / extraction request flow |

A Dataset with zero `DatasetResource` rows just produces an empty Item list for its Collection — no special-casing.

**Collection ← FeatureCollection** (`active=True, public=True`): same field mapping as the Dataset table above (`title`, `description`, `tags`→`keywords`, `source_name`/`source_url`→`providers`, `license`="See source", `spatial_extent`→`extent.spatial`, `temporal_start`/`temporal_end`→`extent.temporal`), plus `summaries: {group_class: [...], group_level: [...]}` populated when set — surfaces boundary hierarchy metadata (e.g. "ADM" / level 2) in the STAC-standard `summaries` slot rather than inventing a custom field.

**Item ← FeatureCollection (synthetic, one per boundary set):** since a boundary set is distributed as a single file rather than a time series, it gets exactly one Item, not a per-`Feature` breakdown (individual `Feature` rows carry no metadata beyond geometry, and a single ADM2 boundary set can be tens of thousands of rows — modeling those as separate Items would be both meaningless and enormous). `id`=`{name}-item`, `collection`=`name`, `geometry`/`bbox`/`datetime` all taken directly from the parent FeatureCollection's own fields (no separate resource to fall back from), `assets: {}`, same `via` link pattern as dataset Items.

**No downloadable assets.** Since raw `DatasetResource` files aren't publicly served, Items omit real asset hrefs entirely rather than including a non-functional or internal-path placeholder. The `via` link is the intended "how do I actually get this data" pointer for a discoverer. This can be revisited if/when raw file serving is added — at that point `assets` gains real entries without any other shape change, since the STAC JSON already has the slot.

## Testing

Mirrors `public_api`'s test structure: `test_collections.py` (covering both Dataset- and FeatureCollection-backed Collections), `test_items.py` (DatasetResource Items and the synthetic boundary Item), `test_search.py`, `test_schema.py` (drf-spectacular schema validity). Two additions beyond that baseline:

- `test_spec_conformance.py` uses `stac-pydantic` (new dev dependency) to validate representative Collection/Item/landing-page payloads against the real STAC/OGC JSON Schema — catches subtle spec violations (datetime formatting, missing required `stac_version`/`type` fields, etc.) that hand-written field-list assertions wouldn't.
- A test asserting the deterministic tie-break `get_collection_source()` must fall back on: when a `Dataset` and a `FeatureCollection` share a name, the `Dataset` wins. (A test that just checks the two name sets are disjoint isn't actually meaningful here — Django's test database starts empty on every run, so that check would trivially pass regardless of what real data looks like. The tie-break test is what's actually enforceable in CI; the "0 collisions in current data" fact from brainstorming was a one-time manual check, not an ongoing guard.)

## Out of scope (this Phase 1)

- Serving raw dataset files / real asset hrefs — no public download mechanism exists for `DatasetResource` data today; this design only adds metadata discovery.
- STAC Transaction extension (create/update/delete Items via the API) — GeoQuery's ingest pipeline remains the only way data enters the catalog.
- Auth/API-key gating — deliberately fully open, unlike `public_api`'s stubbed seam; STAC catalogs are conventionally public.
- Per-dataset real license metadata — `license: "See source"` is a static placeholder; adding a proper `Dataset.license` field is a separate data-modeling change, not part of this work.
- A dedicated STAC server (`stac-fastapi`/`pgstac`) — considered and rejected for Phase 1 as disproportionate to a discovery-only scope; revisit if/when transactions or heavier query needs (CQL2 filtering, etc.) arise.
