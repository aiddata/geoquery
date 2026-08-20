# Public API (Phase A: formalize + document the internal API)

**Status:** Approved, not yet implemented
**Date:** 2026-08-19

## Context

GeoQuery's backend currently exposes DRF endpoints under `/api/{features,datasets,analytics,visualize}/`, consumed only by the SvelteKit frontend. Every view explicitly sets `authentication_classes = []` / `permission_classes = [AllowAny]`, overriding the DRF-wide default (`IsAuthenticatedOrReadOnly` with Session/Token auth) declared in `settings.py`. In practice the API is fully open today — it's just undiscovered, not access-controlled. There is no OpenAPI/schema tooling anywhere in the stack.

A separate, unwired FastAPI module exists at `backend/src/gqcore/api/main.py` (its own `/docs`/`/redoc`/`/openapi.json` comments). It predates the Django migration and is not referenced by docker-compose, any Containerfile, or startup script — confirmed dead code, safe to ignore for this work.

**Goal:** design a path from "open, undocumented, frontend-only" to "public, documented, access-controlled" API, without forcing every future frontend change through a public stability contract, and without duplicating GeoQuery's GeoDjango/PostGIS-heavy spatial logic in a separate service.

User accounts + API key issuance are being developed as a **separate feature**, not part of this work. This design builds the seam that feature will plug into, not the account/key system itself.

## Architecture

A new Django app, `public_api/`, mounted at `/api/public/v1/` in `geoquery/urls.py`.

It does not duplicate business logic: it imports the same model managers/querysets already used by `datasets` and `features` (e.g. `Dataset.objects.filter(active=True, public=True)`, which the existing `DatasetListView` already filters on today). It defines its **own serializers** in `public_api/serializers.py`, decoupled from the frontend's (`datasets/serializers.py`, `features/serializers.py`). This is the core design decision: the frontend's serializers can change for UI needs without silently changing the public contract, because they are different classes reading the same underlying data.

`drf-spectacular` generates the OpenAPI schema, scoped only to `public_api` views via `SPECTACULAR_SETTINGS` and a schema view restricted to the `public_api` URLconf — internal `/api/*` endpoints never appear in public docs. Docs served at `/api/public/v1/docs/` (Swagger UI) and `/api/public/v1/schema/` (raw OpenAPI JSON).

## Versioning

URL-path versioning: `/api/public/v1/...`. A future breaking change ships as `/api/public/v2/...` alongside v1 (not replacing it), with a deprecation window (proposed: 6 months) announced in the docs/changelog before v1 is sunset.

Internal `/api/*` endpoints are unaffected — unversioned, frontend-coupled, free to change, exactly as today.

## Auth seam

`public_api/authentication.py` defines `PublicApiKeyAuthentication`, a DRF `BaseAuthentication` subclass that reads an `Authorization: Api-Key <key>` header and calls `resolve_api_key(key: str) -> PublicApiConsumer | None`.

`PublicApiConsumer` is a minimal protocol: `id`, `rate_limit_tier`, `is_active`. Whatever model the accounts feature produces just needs to satisfy this shape — this design does not define an `ApiKey` model, signup flow, or issuance mechanism; that's owned by the accounts feature.

Until that feature lands, `resolve_api_key` is a stub returning `None` unconditionally, and `public_api` views run with `AllowAny`. This is documented in the API docs themselves as: *"Open during beta. API key required once account-based access launches."* Wiring in the real lookup later is a one-function change against the existing interface, not a rewrite of the auth class or views.

## Rate limiting

`PublicApiThrottle` (DRF throttle class) checks `request.auth` first: if a resolved consumer is present, throttle by `consumer.rate_limit_tier`; otherwise fall back to IP-based throttling (proposed default: 100/hour anonymous). Since the auth seam isn't wired to a real key system yet, every request throttles by IP today — the per-consumer branch exists and is ready, but currently unreachable until `resolve_api_key` returns real consumers.

## Endpoint scope (v1)

Read-only for phase 1, per explicit scope decision — extraction requests (submit/status/results) and visualization/tiles stay internal-only, deferred to a later phase once they can be gated behind real authorization tiers from the accounts feature.

**Datasets** (mirrors `datasets/views.py` logic, against `public_api` serializers):
- `GET /api/public/v1/datasets/` — list (`active=True, public=True`, matching existing internal filtering)
- `GET /api/public/v1/datasets/{name}/`
- `GET /api/public/v1/datasets/categories/`
- `GET /api/public/v1/datasets/coverage/`

**Boundaries** (renamed from the internal "features" model name — clearer for external consumers who don't know GeoQuery's internal terminology):
- `GET /api/public/v1/boundaries/autocomplete/`
- `GET /api/public/v1/boundaries/presets/`

## Error handling

A consistent JSON error envelope scoped to `public_api` only: `{"error": {"code": "...", "message": "..."}}`, via a custom DRF exception handler registered on `public_api` views. Internal endpoints' current (default DRF) error format is untouched — no frontend risk. Throttled requests return `429` with `Retry-After` (DRF's default behavior, no extra work needed).

## Testing

Matches the existing (light) test convention — `APITestCase`-based tests per view, similar in style to `features/tests.py` (currently the only test file in the backend). Two additions beyond that baseline:

- **Serializer field-stability tests**: assert the exact set of keys each `public_api` serializer emits, so an accidental field addition/removal is caught in CI before it becomes an unannounced breaking change to a public contract.
- **Schema-validity test**: hits `/api/public/v1/schema/` and confirms the `drf-spectacular` output is valid OpenAPI.

## Forward-looking note: STAC compatibility

AidData may build a STAC (SpatioTemporal Asset Catalog) interface at some point. STAC API has its own strict spec — specific `Collection`/`Item` JSON shapes, required conformance classes, an OGC API - Features-style `/search` endpoint — so it cannot be served as literally the same responses as `public_api`'s GeoQuery-native JSON.

What does carry over is the reuse pattern established in this design: `Dataset` already holds STAC-relevant metadata (`temporal_start`/`temporal_end`, categories, `Coverage` records for spatial extent). A future STAC layer should be built the same way `public_api` is being built here — its own serializers translating the *same* underlying querysets into STAC's JSON shape — so `Dataset`/`Coverage` becomes a shared data-access layer feeding multiple presentation layers (GeoQuery public API JSON today, STAC JSON potentially later) with no duplicated query logic. No action needed now; this is a constraint to keep in mind so the dataset query layer doesn't end up shaped only for one consumer.

## Out of scope (this design)

- `ApiKey` model, signup/issuance flow, email delivery — owned by the separate accounts feature.
- Extraction request and visualization/tile public endpoints — deferred to a later phase.
- STAC implementation — noted for future compatibility only, not designed here.
- Removal of the dead `gqcore/api/main.py` FastAPI module — out of scope for this work; can be cleaned up separately if desired.
