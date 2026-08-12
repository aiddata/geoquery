# GeoQuery

GeoQuery is a web application for geospatial data extraction. Users select geographic boundaries, choose datasets, and submit extraction requests.

## Project Structure

- `frontend/` — SvelteKit app (Svelte 5, TypeScript, Tailwind CSS, shadcn-svelte)
- `backend/` — Django project with Django REST Framework (Python, PostGIS)
- `backend/src/gqcore/` — Legacy standalone utilities (FastAPI app, raw SQL helpers). **Do not use or extend.** All new backend API work should go through Django REST Framework.

## Development Environment

Development runs entirely through Docker Compose (`docker-compose.yml` at the repo root). Bring the stack up with:

```bash
docker compose up # add --build after changing dependencies or a Containerfile
```

- Frontend (Vite dev server): http://localhost:5173 — this is the origin to use in a browser
- Backend (Django dev server): http://localhost:8000
- Django admin: http://localhost:8000/admin/

Services: `db` (PostGIS), `rabbitmq` (Celery broker), `backend` (Django), `worker-processing` and `worker-background` (Celery workers, one per queue), `beat` (Celery scheduler), `frontend` (Vite).

### Running Commands

The `db` service publishes no port to the host, so `manage.py` cannot be run from the host — it will not reach the database. Run management commands inside the `backend` container:

```bash
docker compose exec backend uv run python manage.py migrate
docker compose exec backend uv run python manage.py createsuperuser
docker compose exec backend uv run python manage.py test
docker compose exec backend uv run python manage.py makemigrations <app>
```

Use `uv` (never `pip`, and never activate a venv) for anything Python. Open a database shell with `docker compose exec db psql -U django_user -d geoquery`.

Frontend commands run in the `frontend` container the same way, e.g. `docker compose exec frontend bun run check`.

### Live Reload and Rebuilds

Only some paths are bind-mounted, so not every edit is picked up live:

- `./backend` → `/app/backend`, and the Django dev server auto-reloads. Editing Python code needs no rebuild, but changing `backend/pyproject.toml` does — dependencies are installed with `uv sync` at image build time.
- `./frontend/src` and `./docs` are mounted; nothing else from `frontend/` is. Changes to `package.json`, `vite.config.ts`, `svelte.config.js`, or `components.json` require `docker compose up --build frontend`, as does anything that adds a dependency.

### Configuration and Data

Secrets come from a `.gitignored` `.env` at the repo root, which Compose reads automatically (`PROTOMAPS_API_KEY`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, and optionally `GITHUB_GIST_TOKEN` and `EMAIL_PASSWORD`). Everything else the containers need is set inline in `docker-compose.yml`.

Three host directories are mounted into the containers, all `.gitignored`:

- `./data` → `/data` — input data (`/data/rasters`, `/data/boundaries`). Dataset JSON `path` fields must use the absolute container path, e.g. `/data/rasters/esa_landcover`. Mounted read-only into `worker-processing`, which is the only worker that gets it.
- `./requests` → `/requests` — extraction results (`settings.REQUESTS_DIR`)
- `./assets` → `/assets` — documentation templates used by `worker-background`

The backend and worker containers run as `${HOST_UID:-1000}:${HOST_GID:-1000}` so files written to those mounts stay owned by the host user. Export `HOST_UID`/`HOST_GID` if your account is not `1000:1000`.

## Backend

### API Framework

Use **Django REST Framework (DRF)** for all backend API endpoints.

- API root: `/api/`
- Features app endpoints: `/api/features/`
- Add new endpoints by creating views in the appropriate Django app (`features/`, `datasets/`, `analytics/`) and wiring them in the app's `urls.py`
- Use DRF serializers for response formatting
- Use Django ORM (not raw SQL) unless PostGIS-specific SQL is required (e.g., MVT tile generation)

### Django Apps

- `features/` — Geographic boundaries: `FeatureCollection`, `Feature`, `FeatMap` models
- `datasets/` — Data products: `Dataset`, `DatasetResource`, `Mapping` models
- `analytics/` — Extraction pipeline: `Coverage`, `ProcessingOption`, `ExtractTask`, `ExtractData`, `Request`, `RequestMap` models

### Key Models

- `FeatureCollection` — A set of geographic boundaries (e.g., "Afghanistan ADM0"). Has `group_name`/`group_level` for grouping subboundaries under a country.
- `Feature` — A single geometry (PostGIS `GeometryField`, SRID 4326)
- `FeatMap` — Links a `FeatureCollection` to its `Feature` geometries with names and attributes
- `Dataset` — A raster or vector data product available for extraction
- `Coverage` — Records which features have been processed for which datasets

### Database

PostgreSQL with PostGIS. Use `django.contrib.gis` for spatial fields and queries.

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

The frontend SvelteKit app communicates with the Django backend API. In development, the Vite dev server proxies or the frontend fetches directly from the Django server (CORS is configured for `localhost:5173`).

## Documentation

The user-facing documentation lives in `docs/` and is built with [Zensical](https://zensical.org). Configuration is `zensical.toml` at the repo root; `.github/workflows/docs.yml` builds the site and publishes it to GitHub Pages.

Docs are built on the host (not in Compose), using the `docs` dependency group:

```bash
uv run --only-group docs zensical serve    # http://127.0.0.1:8001
uv run --only-group docs zensical build --clean
```

Things to know before editing `docs/`:

- **`docs/data_documentation/datasets/` and `docs/data_documentation/boundaries/` are generated**, including their `index.md` files. The `build_dataset_docs_task` and `build_boundary_docs_task` Celery tasks rewrite them from the database nightly (`datasets/tasks/create_docs.py`, `features/tasks/create_docs.py`). Hand edits there are lost — change the generator instead.
- **`nav` in `zensical.toml` is explicit.** A new page will not appear in the site navigation until it is added there.
- **`docs/faq.md` is consumed by the app.** The frontend `HelpPanel` imports it at build time (parsed by `src/lib/utils/parseFaq.ts`), so its structure affects the UI, not just the docs site.

### Changing Documentation

- **Ask the user first before significant changes** — new pages, restructured navigation, rewritten sections, or any change to what the documentation claims the project does. Documentation is user-facing and often reflects decisions that are not visible in the code, so propose the change and wait for confirmation.
- **Make corrective updates without asking.** If the documentation is factually wrong about the current code — a renamed command, a moved path, a stale option, a broken link, a tool that has been replaced — just fix it as part of the work that made it wrong, and say what you changed.
