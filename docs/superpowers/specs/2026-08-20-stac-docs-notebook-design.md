# STAC API docs + demo notebook

**Status:** Approved, not yet implemented
**Date:** 2026-08-20

## Context

`public_api` (Phase A, shipped 2026-08-20) got a living demo notebook — `docs/using-geoquery/tutorials/public-api-demo.ipynb`, linked from `docs/using-geoquery/tutorials/index.md` — walking every endpoint with real `requests` calls against a running dev server, rather than a hand-written prose reference that drifts out of sync. No separate written markdown page exists for `public_api`; the notebook plus the auto-generated Swagger docs (`/api/public/v1/docs/`) are the whole documentation surface.

`stac_api` (Phase 1, shipped 2026-08-20) now needs the same treatment. It's a different API (different base URL, different JSON shapes, a different reason to exist — spec-conformant discovery rather than a GeoQuery-native contract) so it gets its own notebook, not new sections bolted onto the existing one.

**Goal:** a `stac-api-demo.ipynb` that walks every `stac_api` endpoint, in the same style and with the same "runnable, re-run it and it just works against live data" philosophy as `public-api-demo.ipynb`, plus a closing section demonstrating the catalog against a real third-party STAC client (`pystac-client`) — a concrete demonstration of the interoperability goal that motivated building this as a spec-conformant STAC API rather than a bespoke one.

## Scope decision: no separate written docs page

Matches `public_api`'s precedent exactly: one `tutorials/index.md` bullet linking to the notebook, nothing else. The notebook's markdown cells carry the explanation (what each endpoint does, why); `/api/stac/v1/docs/`'s Swagger UI covers the raw schema. A dedicated prose page explaining "what is STAC" was considered and explicitly not chosen — proportional to what `public_api` got, and the notebook plus Swagger already cover both "how do I use this" and "what does this return."

## Notebook structure

`docs/using-geoquery/tutorials/stac-api-demo.ipynb`, mirroring `public-api-demo.ipynb`'s cell pattern (one markdown cell explaining an endpoint, one code cell calling it, chaining real ids resolved from earlier cells rather than hardcoding them):

1. **Title + intro** — what this notebook is, that it's meant to be re-run and kept current as `stac_api` changes.
2. **Setup** — `%pip install requests pystac-client -q`; a `BASE_URL = "http://localhost:8000/api/stac/v1"` constant; the same `call(method, path, **kwargs)` pretty-printing helper `public-api-demo.ipynb` already establishes (copied, not imported — the two notebooks are independent, matching how neither shares code with the other today).
3. **Landing page** (`GET /`) — show the STAC Catalog shape, `conformsTo`, and the `links` a client would actually follow (`data`, `search`, `service-doc`).
4. **Conformance** (`GET /conformance/`) — the conformance class list, framed as "this is how a client knows what it can ask this catalog to do."
5. **Browse collections** (`GET /collections/`) — the combined Dataset + FeatureCollection list; note in prose that both dataset-backed and boundary-backed collections are mixed together here.
6. **Get a collection by name** (`GET /collections/{name}/`) — uses the first collection from step 5.
7. **Browse items in a collection** (`GET /collections/{name}/items/`) — pick a dataset-backed collection specifically (search the step-5 results for one whose id doesn't look like a boundary preset, or just take the first and note what it is); show the `numberMatched`/`numberReturned`/pagination `links` shape.
8. **Get an item by id** (`GET /collections/{name}/items/{item_id}/`) — uses the first item from step 7; call out the `via` link as "this is how a discoverer gets from metadata to actually requesting the data."
9. **A boundary-backed collection's synthetic item** — deliberately pick a `FeatureCollection`-backed collection from step 5's results and show its single `{name}-item`. This is the one part of the shipped design most worth calling out explicitly (a boundary set is one Item, not one per administrative unit), so it gets its own cell rather than being folded into step 7-8's generic walkthrough.
10. **Search** (`GET`/`POST /search/`) — one cell with no params (everything, up to `limit`), one with a `bbox`/`datetime`/`collections` filter combination built from ids/extents resolved in earlier cells (not hardcoded), and one showing the POST form with the same filters as a JSON body — directly demonstrating GET/POST equivalence, which was a stated acceptance criterion during implementation.
11. **Real STAC client interop** (`pystac-client`) — `from pystac_client import Client`; `Client.open(BASE_URL)`; `catalog.get_collections()`; `catalog.search(bbox=..., datetime=..., collections=...).item_collection()`. This is the section that concretely shows "a hand-rolled server can be exactly as interoperable as a purpose-built STAC server," using a real ecosystem library rather than another `requests` call.
12. **Keeping this notebook current** — closing markdown cell, same framing as `public-api-demo.ipynb`'s: update the matching cell in the same PR that changes an endpoint; `/api/stac/v1/schema/` is the source of truth if this notebook and the real API ever disagree.

## Dependency change

`pystac-client` added to root `pyproject.toml`'s `notebooks` dependency-group (same group `ipykernel` already lives in, needed for the Jupyter kernel itself). It's a lightweight, pure-Python client (`pystac`, `requests`, `python-dateutil` as its own deps) — no conflict risk with anything already pinned.

## Docs change

One new bullet in `docs/using-geoquery/tutorials/index.md`, directly below the existing Public API demo line, same format:

```
- [STAC API demo](stac-api-demo.ipynb) — a runnable notebook walking through every `/api/stac/v1/` endpoint, including a real STAC-client (`pystac-client`) interop example, kept up to date as the API changes.
```

## Testing / verification

Not unit-testable in the usual sense (it's a notebook, not application code) — verification is running it end-to-end against the live dev server and confirming every cell executes without error and produces sensible output, the same way `public-api-demo.ipynb` was verified when it shipped. No new automated test is added for this work.

## Out of scope

- A dedicated written "what is STAC" prose page — explicitly decided against, see Scope decision above.
- Any change to `stac_api`'s actual endpoints, serializers, or behavior — this is documentation-only work layered on top of the already-shipped, already-reviewed Phase 1 API.
- Publishing/registering the catalog with any external STAC index/aggregator — out of scope for this internal documentation task.
