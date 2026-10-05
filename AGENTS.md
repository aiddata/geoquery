# GeoQuery

GeoQuery is a web application for geospatial data extraction. Users select geographic boundaries, choose datasets, and submit extraction requests.

## Permission to Commit, Push, and Deploy

**Do not commit, push, merge, or deploy without the user's explicit permission for that action and the current changes.** Permission to edit code, fix a bug, run tests, or assess a proposal does not authorize any of these actions. Statements such as "this needs a deploy" describe a requirement; they are not instructions to deploy.

- Treat committing, pushing/merging, and deploying as separate permissions. Approval for one does not imply approval for the others. A single explicit request may authorize multiple actions, but only within its stated scope; approval for a previous task does not carry over to new work.
- Deployment includes indirect triggers: pushing a commit with a `[DEPLOY-X.Y.Z]` marker, dispatching or rerunning a release workflow, changing deployment repositories or image tags, and mutating a live cluster. Do not use an indirect trigger to bypass deployment approval.
- Complete authorized local edits and relevant checks first. Then present the concrete changes and validation results, and request any missing permission before committing, pushing, merging, or deploying. Leave changes uncommitted until committing is explicitly authorized.

## Project Structure

- `frontend/` — SvelteKit app (Svelte 5, TypeScript, Tailwind CSS, shadcn-svelte)
- `backend/` — Django project with Django REST Framework and a FastMCP server (Python, PostGIS)

## Development Environment

Development runs entirely through Docker Compose (`docker-compose.yml` at the repo root). Bring the stack up with:

```bash
docker compose up # add --build after changing dependencies or a Containerfile
```

- Frontend (Vite dev server): http://localhost:5173 — this is the origin to use in a browser
- Backend (Django dev server): http://localhost:8000
- Django admin: http://localhost:8000/admin/
- MCP server (streamable HTTP): http://localhost:8001/mcp

Services: `db` (PostGIS), `rabbitmq` (Celery broker), `backend` (Django), `mcp` (FastMCP), `worker-processing` (extract worker, claiming extract tasks from Postgres), `worker-background` (Celery worker), `beat` (Celery scheduler), `frontend` (Vite).

### Running Commands

The `db` service publishes no port to the host, so `manage.py` cannot be run from the host — it will not reach the database. Run management commands inside the `backend` container:

```bash
docker compose exec backend uv run python manage.py migrate
docker compose exec backend uv run python manage.py createsuperuser
docker compose exec backend uv run python manage.py test
docker compose exec backend uv run python manage.py makemigrations <app>
# After configuring authenticated MCP sign-in (idempotent):
docker compose exec backend uv run python manage.py ensure_mcp_oidc_client
```

Use `uv` (never `pip`, and never activate a venv) for anything Python. Open a database shell with `docker compose exec db psql -U django_user -d geoquery`.

Frontend commands run in the `frontend` container the same way, e.g. `docker compose exec frontend bun run check`.

### Live Reload and Rebuilds

Only some paths are bind-mounted, so not every edit is picked up live:

- `./backend` → `/app/backend` in `backend`, `mcp`, both workers, and `beat`. The Django dev server auto-reloads; the MCP server, both workers, and beat do not, so restart those services after changing code they load. Python edits need no rebuild, but changing `backend/pyproject.toml` does — dependencies are installed with `uv sync` at image build time.
- `./frontend/src` and `./docs` are mounted; nothing else from `frontend/` is. Changes to `package.json`, `vite.config.ts`, `svelte.config.js`, or `components.json` require `docker compose up --build frontend`, as does anything that adds a dependency.

### Configuration and Data

Local secrets and deployment-specific URLs come from a `.gitignored` `.env` at the repo root, which Compose reads automatically. Web-app integrations use `PROTOMAPS_API_KEY`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, and optionally `GITHUB_GIST_TOKEN` and `EMAIL_PASSWORD`. Authenticated MCP sign-in uses `OIDC_PRIVATE_KEY`, `MCP_OIDC_CLIENT_ID`, and `MCP_OIDC_CLIENT_SECRET`; set a stable `MCP_JWT_SIGNING_KEY` so client registrations survive secret rotation. The MCP server deliberately falls back to anonymous, public-data-only access in local debug mode when its OIDC client is not configured.

Three host directories are mounted into the containers:

- `./data` → `/data` — `.gitignored` input data (`/data/rasters`, `/data/boundaries`). Dataset JSON `path` fields must use the absolute container path, e.g. `/data/rasters/esa_landcover`. Mounted read-write into `backend` for ingestion commands and read-only into `worker-processing` for extraction.
- `./requests` → `/requests` — `.gitignored` extraction results (`settings.REQUESTS_DIR`), mounted into `backend`, `mcp`, and both workers
- `./assets` → `/assets` — tracked documentation templates and papers used to build request outputs, mounted into `worker-background` (and copied into the backend image for production)

The backend, MCP, and worker containers run as `${HOST_UID:-1000}:${HOST_GID:-1000}` so files written to those mounts stay owned by the host user. Export `HOST_UID`/`HOST_GID` if your account is not `1000:1000`.

## Backend

### API Framework

Use **Django REST Framework (DRF)** for all backend API endpoints.

- Internal SPA endpoints live under `/api/features/`, `/api/datasets/`, `/api/analytics/`, and `/api/visualize/`
- The read-only public API lives under `/api/public/v1/`; its OpenAPI schema and Swagger UI are at `schema/` and `docs/` beneath that prefix
- The read-only STAC API lives under `/api/stac/v1/`
- Authentication, runtime configuration, and precomputed statistics live under `/api/_allauth/` or `/api/auth/`, `/api/config/`, and `/api/stats/`
- Add new endpoints by creating views in the app that owns the behavior and wiring them in that app's `urls.py`
- Use DRF serializers for response formatting
- Use Django ORM (not raw SQL) unless PostGIS-specific SQL is required (e.g., MVT tile generation)

### Backend Apps and Modules

- `accounts/` — Custom users, django-allauth integration, and GeoQuery's OIDC provider
- `features/` — Geographic boundaries: `FeatureCollection`, `Feature`, `FeatMap` models
- `datasets/` — Data products: `Dataset`, `DatasetResource`, `Mapping` models
- `analytics/` — Extraction pipeline: `Coverage`, `ProcessingOption`, `ExtractTask`, `ExtractData`, `Request`, `RequestMap` models
- `catalog/` — Catalog-based access control for datasets, feature collections, and processing options
- `visualize/` — Request visualization and export endpoints
- `public_api/` — Versioned public dataset and boundary API
- `stac_api/` — STAC discovery API
- `mcp_server/` — FastMCP tools, prompts, authentication, and server command
- `stats/` — Precomputed public usage statistics

### Key Models

- `FeatureCollection` — A set of geographic boundaries (e.g., "Afghanistan ADM0"). Has `group_name`/`group_level` for grouping subboundaries under a country.
- `Feature` — A single geometry (PostGIS `GeometryField`, SRID 4326)
- `FeatMap` — Links a `FeatureCollection` to its `Feature` geometries with names and attributes
- `Dataset` — A raster or vector data product available for extraction
- `Coverage` — Records which features have been processed for which datasets

### Database

PostgreSQL with PostGIS. Use `django.contrib.gis` for spatial fields and queries.

**Read `docs/get-involved/contributing/dev/database.md` before writing queries against `extract_tasks` or
`extract_data`, adding an index, adding a background task, or changing cluster
settings.** It records the decisions governing this database and the justification
for each — most exist because of a production incident or a measurement. Its
"Working rules" section is the short version.

The one rule worth repeating here: `extract_tasks` and `extract_data` are LIST
partitioned on `dataset_id` with `PRIMARY KEY (dataset_id, id)`, so **every query
must filter on `dataset_id`** — including through joins and relation traversals.
Filtering on `id` alone cannot seek the index and scans all 56 partitions
(4.1 s versus 0.2 ms, measured on production).

## Frontend

### Framework

SvelteKit with Svelte 5 runes syntax (`$state`, `$derived`, `$effect`, `$props`).

### Package Manager

Use `bun` instead of npm/yarn/pnpm:
- `bun install` for dependencies
- `bun run dev` for dev server
- `bun run build` for production build

### UI Components

Uses `shadcn-svelte` (in `src/lib/components/ui/`) and Tailwind CSS.

### Frontend-Backend Communication

The frontend SvelteKit app communicates with the Django backend API. In development, Vite proxies `/api` to the `backend` service while preserving the browser-facing Host header; this is required for OAuth redirect URLs. Django also allows credentialed CORS from `localhost:5173` and `127.0.0.1:5173`.

## Documentation

The user-facing documentation lives in `docs/` and is built with [Zensical](https://zensical.org). Configuration is `zensical.toml` at the repo root; `.github/workflows/docs.yml` builds the site and publishes it to GitHub Pages.

Docs are built on the host (not in Compose), using the `docs` dependency group:

```bash
uv run --only-group docs zensical serve    # http://127.0.0.1:8001
uv run --only-group docs zensical build --clean
```

The docs dev server and the Compose `mcp` service both use host port 8001. Stop `mcp` before running `zensical serve`, or configure one of them to use a different port.

Things to know before editing `docs/`:

- **`docs/data_documentation/datasets/` and `docs/data_documentation/boundaries/` are generated**, including their `index.md` files. The `build_dataset_docs_task` and `build_boundary_docs_task` Celery tasks rewrite them from the database nightly (`datasets/tasks/create_docs.py`, `features/tasks/create_docs.py`). Hand edits there are lost — change the generator instead.
- **`nav` in `zensical.toml` is explicit.** A new page will not appear in the site navigation until it is added there.
- **`docs/faq.md` is consumed by the app.** The frontend `HelpPanel` imports it at build time (parsed by `src/lib/utils/parseFaq.ts`), so its structure affects the UI, not just the docs site.

### Changing Documentation

- **Ask the user first before significant changes** — new pages, restructured navigation, rewritten sections, or any change to what the documentation claims the project does. Documentation is user-facing and often reflects decisions that are not visible in the code, so propose the change and wait for confirmation.
- **Make corrective updates without asking.** If the documentation is factually wrong about the current code — a renamed command, a moved path, a stale option, a broken link, a tool that has been replaced — just fix it as part of the work that made it wrong, and say what you changed.
