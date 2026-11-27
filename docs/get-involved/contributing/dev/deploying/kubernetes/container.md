---
description: "How GeoQuery's backend and frontend container images are built by GitHub Actions, where they're published, and how a release picks them up."
---

# Container images

GeoQuery has two images, both built by GitHub Actions on pushes to `main` and published to the GitHub Container Registry:

| Image | Built from | Workflow | Rebuilt when these change |
|---|---|---|---|
| `ghcr.io/aiddata/geoquery-backend` | `backend/Containerfile` | `Build backend container` (`build-backend.yaml`) | `backend/**`, `pyproject.toml`, `uv.lock`, the workflow |
| `ghcr.io/aiddata/geoquery-frontend` | `frontend/Containerfile` | `Build frontend container` (`build-frontend.yaml`) | `frontend/**`, `docs/faq.md`, the workflow |

Each image is tagged with the short commit SHA it was built from. Nobody builds or pushes images by hand.

The backend image serves every backend workload: the web backend, the MCP server, both kinds of worker, beat, the migration Job and the import pod. Only the command differs.

## What's in them

- **Backend**: Python 3.12 with GDAL, GEOS and PROJ, dependencies installed by `uv sync --frozen`, the Django project at `/app/backend`, `assets/` at `/app/assets`, and collected static files for WhiteNoise. It runs as a non-root user (UID 1000).
- **Frontend**: a multi-stage Bun build. The `dev` stage is what Compose runs locally; the production stage holds the `adapter-node` build and production dependencies only. The build copies `docs/` in, because the app imports `docs/faq.md` at build time, which is why an FAQ edit rebuilds the frontend.

The build context for both is the repository root.

## Images at different commits

Each workflow only runs when its own paths change, so the two images are routinely built from different commits. When a release runs, `Deploy GeoQuery` uses this commit's image for whichever side rebuilt, and keeps the chart's current tag for the side that didn't. It refuses to deploy a commit whose triggered builds haven't all succeeded. See [Deploying with Flux](flux.md).

## Forcing a rebuild

Touch the image's workflow file (it's in its own path filter) and merge that, for example to pick up a new base image without an application change.

## Building locally

Compose builds both images for local development (`docker compose up --build`); the backend image is shared by every backend service under the name `geoquery-backend`. To build one as CI does:

```bash
docker build -f backend/Containerfile -t geoquery-backend .
docker build -f frontend/Containerfile -t geoquery-frontend .
```
