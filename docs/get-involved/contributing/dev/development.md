---
description: "Running GeoQuery locally with Docker Compose: the services, configuration, data directories, management commands, live reload, and loading data."
---

# Local development

The whole stack runs locally with Docker Compose, from `docker-compose.yml` at the repository root.

## Prerequisites

- Docker with Compose v2 (Podman with Compose compatibility also works).
- [uv](https://docs.astral.sh/uv/), only if you want to build these docs or run Python tools on the host.

## Starting the stack

```bash
docker compose up --build            # web app, API, MCP server, Celery
docker compose --profile extract up  # also the extract worker
```

| Service | What it runs | Host port |
|---|---|---|
| `db` | PostGIS 17 (`postgis/postgis:17-master`) | none |
| `rabbitmq` | Celery's broker | none |
| `backend` | Django dev server (`runserver`) | [8000](http://localhost:8000) |
| `mcp` | MCP server, streamable HTTP at `/mcp` | [8001](http://localhost:8001/mcp) |
| `worker-processing` | Extract worker (`run_extract_worker --concurrency 2`). Only with `--profile extract` | none |
| `worker-background` | Celery worker on the `background` queue | none |
| `beat` | Celery beat scheduler | none |
| `frontend` | SvelteKit + Vite dev server | [5173](http://localhost:5173) |

Use **http://localhost:5173** in the browser. Vite proxies `/api` to the backend and keeps the browser's `Host` header, which GitHub sign-in needs for its redirect URLs. The Django admin is at http://localhost:8000/admin/.

The extract worker is behind a profile because it competes for CPU with everything else and isn't needed for most frontend or API work. Without it, requests stay queued.

## Configuration

Secrets and deployment-specific URLs come from a git-ignored `.env` at the repository root, which Compose reads automatically. Nothing in it is required to start the stack; each variable turns on one integration:

| Variable | Turns on |
|---|---|
| `PROTOMAPS_API_KEY` | The basemap |
| `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` | Signing in with GitHub |
| `GITHUB_GIST_TOKEN` | Notebook export to a gist (beta) |
| `EMAIL_PASSWORD`, `DJANGO_EMAIL_BACKEND` | Sending real email. In debug mode email is printed to the sending container's log, unless `DJANGO_EMAIL_BACKEND` is set to `django.core.mail.backends.smtp.EmailBackend` |
| `OIDC_PRIVATE_KEY`, `MCP_OIDC_CLIENT_ID`, `MCP_OIDC_CLIENT_SECRET`, `MCP_JWT_SIGNING_KEY` | Signed-in MCP access. Without them, the MCP server falls back to anonymous, public-data-only access in debug mode |

[Configuration](configuration.md) lists every setting.

## Data directories

Three host directories are mounted into the containers:

| Host | Container | Holds |
|---|---|---|
| `./data` | `/data` | Input rasters and boundary files (git-ignored). Dataset `path` fields must use the container path, such as `/data/rasters/esa_landcover`. Read-write in `backend` for ingest, read-only in the extract worker |
| `./requests` | `/requests` | Request outputs, the stats snapshot and the data docs bundle (git-ignored) |
| `./assets` | `/assets` | Templates and the GeoQuery paper copied into each request's output (tracked) |

The backend, MCP and worker containers run as `${HOST_UID:-1000}:${HOST_GID:-1000}`, so files they write stay owned by you. Export `HOST_UID` and `HOST_GID` if your account isn't `1000:1000`.

## Running commands

The database publishes no port to the host, so `manage.py` must run inside a container:

```bash
docker compose exec backend uv run python manage.py migrate
docker compose exec backend uv run python manage.py createsuperuser
docker compose exec backend uv run python manage.py shell
docker compose exec backend uv run python manage.py makemigrations <app>
docker compose exec db psql -U django_user -d geoquery    # database shell
```

If the stack isn't running, use `docker compose run --rm backend …` instead of `exec`. Frontend commands run in the `frontend` container the same way, such as `docker compose exec frontend bun run check`.

Use `uv` for anything Python: never `pip`, and never activate a virtualenv. [Management commands](management-commands.md) lists the project's own commands.

## Live reload and rebuilds

Only some paths are mounted, so not every change is picked up live:

- **`./backend`** is mounted into `backend`, `mcp`, both workers and `beat`. The Django dev server reloads on its own. The MCP server, the workers and beat don't: restart them (`docker compose restart worker-background beat mcp`) after changing code they load.
- **`./frontend/src` and `./docs`** are mounted into `frontend`, and Vite pushes changes to the browser. Nothing else under `frontend/` is mounted.

Rebuild (`docker compose up --build <service>`) after changing:

- `pyproject.toml` or `uv.lock` (Python dependencies are installed at build time)
- `frontend/package.json`, `bun.lock`, `vite.config.ts` or `components.json`
- either `Containerfile`

## Loading data

A new database has no boundaries or datasets. Load a few to work with:

```bash
# A country's geoBoundaries sets
docker compose exec backend uv run python manage.py ingest_geoboundaries --help

# A dataset from the geo-datasets repository, by name
docker compose exec backend uv run python manage.py ingest_dataset esa_landcover
```

Rasters must be under `./data`, at the path the dataset's ingest JSON names. [Ingest data](deploying/kubernetes/ingest-data.md) covers the ingest commands, and `ensure_dataset_partitions` creates the per-dataset partitions if a dataset was added some other way.

## Building these docs

The docs are built on the host, not in Compose:

```bash
uv run --only-group docs zensical serve        # http://127.0.0.1:8001
uv run --only-group docs zensical build --clean
```

The docs server and the `mcp` service both use port 8001: stop `mcp` first, or pass the docs server another address. The dataset and boundary pages under `data_documentation/` are generated, not committed; preview them with `manage.py build_data_docs --out <dir>`.

## Starting over

The database lives in the `pgdata` volume, which survives `docker compose down`. To wipe it:

```bash
docker compose down -v
```
