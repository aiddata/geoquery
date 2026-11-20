---
description: "How GeoQuery fits together: the SvelteKit frontend, the Django backend and its apps, the extract worker, Celery, the MCP server, PostgreSQL, and how a request flows through them."
---

# Architecture

GeoQuery is a SvelteKit frontend and a Django backend sharing one PostgreSQL + PostGIS database. Extraction runs in a separate worker fleet that claims its work straight from the database, and a Celery worker runs everything else that happens in the background.

## Components

| Component | What it is | Runs as |
|---|---|---|
| **Frontend** | SvelteKit 3 / Svelte 5 app (`frontend/`): the map, Customize and Review steps, request pages, stats, accounts | `adapter-node` server; `bun run dev` locally |
| **Backend** | Django + Django REST Framework (`backend/`): every API, the admin, authentication | `uvicorn geoquery.asgi:application`; `runserver` locally |
| **Extract worker** | `manage.py run_extract_worker` (`analytics/extract_worker.py`): computes extracts | Processing pods, autoscaled on demand; `worker-processing` locally |
| **Background worker** | Celery on the `background` queue: request sweeps, sync, coverage, docs, stats, email | Background pods; `worker-background` locally |
| **Beat** | Celery beat: the schedule that drives the background worker ([Background jobs](background-jobs.md)) | One pod; `beat` locally |
| **MCP server** | FastMCP server (`mcp_server/`, `manage.py run_mcp`) so AI assistants can search, explore and submit requests | Its own pod; `mcp` locally on port 8001 |
| **PostgreSQL** | PostgreSQL 17 + PostGIS, run by CloudNativePG, behind pgBouncer in transaction mode ([Database](database.md)) | CNPG cluster with standbys; `db` locally |
| **RabbitMQ** | Celery's broker | One pod; `rabbitmq` locally |
| **Proxy** | nginx in front of everything in the cluster: `/api/…` to the backend, MCP and OAuth paths to the MCP server, the rest to the frontend | One pod (chart only) |

## Backend apps

| App | Owns |
|---|---|
| `features` | Boundaries: `FeatureCollection` (a boundary set), `Feature` (a geometry), `FeatMap` (a feature's membership of a set, with its attributes). Vector tiles, simplified geometries, boundary search and presets |
| `datasets` | `Dataset`, `DatasetResource` (one raster or file, usually one time period), `Mapping` (category names), processing options; ingest and the generated data docs |
| `analytics` | Requests and extraction: `Request`, `RequestMap`, `ExtractTask`, `ExtractData`, `Coverage`, `ProcessingOption`, the extract worker, sync, request sweeps and output files, share links and recipes |
| `accounts` | The custom `User`, django-allauth (GitHub sign-in, headless API for the SPA), GeoQuery's own OIDC provider (used by the MCP server), beta feature flags |
| `catalog` | Catalogs: named bundles of datasets, boundary sets and processing options that non-public access is granted on |
| `public_api` | The read-only public API under `/api/public/v1/` ([APIs](apis.md)) |
| `stac_api` | The STAC API under `/api/stac/v1/` |
| `stats` | The hourly stats snapshot and the live status check behind `/stats` |
| `visualize` | The beta map/visualize views and notebook export |
| `mcp_server` | The MCP server: tools, prompts, guides, OAuth |

## How a request flows

1. **Building it.** The frontend keeps the request in Svelte stores: the selection, the cart of datasets and options, and the form. The tab's state is saved to `sessionStorage`, so it survives a refresh ([Frontend](frontend.md)).
2. **Submitting.** `POST /api/analytics/requests/` validates it and `create_request` (`analytics/services.py`) writes a `Request` at status `4` and returns at once.
3. **Materializing.** A background task creates the request's task rows, reusing any that already exist, and moves it to queued (`-1`).
4. **Extracting.** Extract worker slots claim pending task rows, compute them from the rasters or vector data under `/data`, and write `extract_data`. Most of a typical request's tasks already exist from background extraction, so they're done before it's submitted.
5. **Sweeping.** Every five minutes `process_user_requests` checks queued requests. When all of a request's tasks are done it builds the output (CSV, GeoPackage, documentation, JSON) under `REQUESTS_DIR`, marks it complete (`1`) and emails the requester.

[Request Lifecycle](request-lifecycle.md) covers the statuses and recovery in detail.

## Background extraction

Most data is extracted before anyone asks for it. For every active dataset, processing option and boundary set, the extract worker works through features in pages it **leases**, and creates task rows only when a page is finished. Changes to inputs (a new boundary set, an edited dataset) are recorded by database triggers and reconciled by **sync** on the background worker. [Extraction Workflow](extraction-workflow.md) explains it end to end, and [Database §12](database.md#12-background-extraction-pair-cursor-leases) lists its contracts.

## Storage

| Location | Holds | Setting |
|---|---|---|
| PostgreSQL | Everything but files. `extract_tasks` and `extract_data` are partitioned by dataset | `PG_RW_*`, `PG_RO_*` |
| `/data` | Input rasters and boundary files, read by ingest and the extract worker | dataset `path` fields |
| `/requests` | Request outputs, the stats snapshot, the data docs bundle | `REQUESTS_DIR` |
| `/app/assets` | Templates and the GeoQuery paper copied into every request's output | `ASSETS_DIR` |

## Access control

Two independent gates decide what a user can see:

- **Visibility of data.** A dataset, boundary set or processing option is visible if it's active and either `public` or in a catalog the user has access to (`catalog/access.py`). Grants are made on catalogs in the Django admin, never on individual resources.
- **Beta features.** `accounts/features.py` lists features (`BETA_FEATURES`) that only beta testers see: anyone with the `accounts.beta_tester` permission, plus superusers. The frontend reads the caller's set from `/api/config/`. Release a feature by removing it from the set.
