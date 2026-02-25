# GeoQuery

GeoQuery is a web application for geospatial data extraction. Users select geographic boundaries, choose datasets, and submit extraction requests.

## Project Structure

- `frontend/` — SvelteKit app (Svelte 5, TypeScript, Tailwind CSS, shadcn-svelte)
- `backend/` — Django project with Django REST Framework (Python, PostGIS)
- `backend/src/gqcore/` — Legacy standalone utilities (FastAPI app, raw SQL helpers). **Do not use or extend.** All new backend API work should go through Django REST Framework.

## Backend

### API Framework

Use **Django REST Framework (DRF)** for all backend API endpoints. Do not use the FastAPI app in `backend/src/gqcore/api/`. That code is legacy and should not be extended.

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
