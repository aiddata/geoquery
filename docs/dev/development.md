# Docker Compose Development

This guide covers running the full GeoQuery stack locally with Docker Compose.

## Prerequisites

- Docker (or Podman with `docker-compose` compatibility)

## Starting the stack

```
docker compose up --build
```

This starts seven services:

| Service | Description | Port |
|---|---|---|
| **db** | PostGIS 17 database | 5432 |
| **rabbitmq** | Message broker for Celery | 5672 (AMQP), 15672 (management UI) |
| **backend** | Django REST API | 8000 |
| **worker-processing** | Celery worker on the `processing` queue (raster extracts; mounts `/data`) | — |
| **worker-background** | Celery worker on the `background` queue (coverage, docs, maintenance) | — |
| **beat** | Celery beat scheduler | — |
| **frontend** | SvelteKit + Vite dev server | 5173 |

Open [http://localhost:5173](http://localhost:5173) to access the frontend.

## Hot reloading

Both the frontend and backend hot-reload during development:

- **Frontend** — `./frontend/src` is bind-mounted into the container. Vite picks up changes via polling and pushes updates to the browser with HMR.
- **Backend** — `./backend` is bind-mounted into the container. Django's `runserver` watches for Python file changes and restarts automatically.

No rebuild is needed for source code changes.

## Database migrations

Run migrations against the running `backend` container:

```
docker compose exec backend uv run python manage.py migrate
```

If the containers aren't running yet, use `run` instead:

```
docker compose run --rm backend uv run python manage.py migrate
```

Other common management commands work the same way:

```
docker compose exec backend uv run python manage.py makemigrations
docker compose exec backend uv run python manage.py createsuperuser
docker compose exec backend uv run python manage.py shell
```

## When to rebuild

You need to pass `--build` (or run `docker compose build`) when:

- **Python dependencies change** — edits to `pyproject.toml` or `uv.lock`
- **Frontend dependencies change** — edits to `package.json` or `bun.lock`
- **Containerfile changes** — any modification to `backend/Containerfile` or `frontend/Containerfile`

You do **not** need to rebuild for:

- Python or Svelte/TypeScript source changes (hot-reloaded via bind mounts)
- Environment variable changes in `docker-compose.yml` (applied on `docker compose up`)

## Persistent data

The PostgreSQL data is stored in a named Docker volume (`pgdata`). It survives `docker compose down`. To wipe the database and start fresh:

```
docker compose down -v
```
