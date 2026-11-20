---
description: "Every environment variable GeoQuery's backend reads, grouped by what it controls, with defaults."
---

# Configuration

The backend reads its configuration from environment variables in `backend/geoquery/settings.py`. Locally they come from `.env` and `docker-compose.yml`; in the cluster, from the Helm chart's values and secrets ([Helm chart](deploying/kubernetes/helm-chart.md)).

Many settings have a long comment in `settings.py` recording why the default is what it is, often with a production measurement. Read it before changing one.

## Django and URLs

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_DEBUG` | `False` | Debug mode. Also switches email to the console and the MCP server's anonymous fallback |
| `DJANGO_SECRET_KEY` | none (an insecure key in debug) | Django's secret key |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated origins |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | The public site; used in emails, sign-in redirects and OAuth |
| `DOWNLOAD_BASE_URL` | `http://localhost:8000` | Base of request download links |
| `LEGACY_DOWNLOAD_BASE_URL` | unset | Base of downloads for requests from the previous GeoQuery |
| `TOKEN_EXPIRY_MONTHS` | `6` | How long an emailed request-history link stays valid |

## Database

Two sets of connection variables: `PG_RW_*` for the read/write pgBouncer, and `PG_RO_*` for the read-only one in front of the standbys. A process without `PG_RO_*` sends its `.using("replica")` reads to the primary.

| Variable | Default | Purpose |
|---|---|---|
| `PG_RW_HOST`, `PG_RW_PORT`, `PG_RW_DBNAME`, `PG_RW_USER`, `PG_RW_PASSWORD` | `localhost`, `5432`, `geoquery`, `django_user`, empty | The primary, through pgBouncer |
| `PG_RO_HOST`, … | the `PG_RW_*` values | The standbys |
| `PG_SSL_MODE` | `prefer` | libpq `sslmode` |
| `PG_POOL_MAX_SIZE` | `0` (no pool) | Client-side connection pool per alias per process. Set for the web backend only ([Database §5](database.md#5-connection-pooling-transaction-scoped-and-budgeted)) |

## Files

| Variable | Default | Purpose |
|---|---|---|
| `REQUESTS_DIR` | `<repo>/requests` | Request outputs, the stats snapshot, the data docs bundle |
| `ASSETS_DIR` | `<repo>/assets` | Files copied into every request's output |
| `DOCS_DIR` | `<repo>/docs` | The docs tree; the MCP server reads `citing.md` from it |

## Integrations

| Variable | Purpose |
|---|---|
| `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` | GitHub sign-in |
| `EMAIL_PASSWORD` | SMTP password for `noreply@aiddata.wm.edu` |
| `DJANGO_EMAIL_BACKEND` | Overrides the email backend (console in debug, SMTP otherwise) |
| `PROTOMAPS_API_KEY` | The basemap; passed to the frontend through `/api/config/` |
| `GITHUB_GIST_TOKEN`, `EXPORT_GIST_TTL_SECONDS` (`3600`) | Notebook export to a gist (beta), and how long those gists live |
| `DATASET_CATEGORIES` | A JSON object replacing the dataset category menu (category → tags) |

## Celery

| Variable | Default | Purpose |
|---|---|---|
| `CELERY_BROKER_URL` | `amqp://guest:guest@localhost:5672//` | RabbitMQ |
| `CELERY_RESULT_BACKEND` | `django-db` | Where task results go ([Database §9](database.md#9-celery-result-backend)) |
| `CELERY_RESULT_EXPIRES` | `86400` | Seconds before `celery.backend_cleanup` removes a result |

## Extraction

| Variable | Default | Purpose |
|---|---|---|
| `EXTRACT_TASK_CLAIM_BATCH` | `64` | Task rows one worker slot claims at once ([Database §2](database.md#2-task-claiming-serialized-on-purpose-amortized-by-batching)) |
| `EXTRACT_TASK_SYNCHRONOUS_COMMIT` | `0` | `1` makes task-row writes commit synchronously |
| `EXTRACT_WORKER_IDLE_SECONDS` | `60` | How long an idle slot waits before looking again |
| `EXTRACT_WORKER_DRAIN_SECONDS` | `840` | How long a stopping worker may spend finishing a lease page |
| `STALE_TASK_MINUTES` | `30` | When a running task row is presumed abandoned |
| `MAX_EXTRACT_TASK_ATTEMPTS` | `5` | Attempts before a failing task is left failed |
| `EXTRACT_TASK_LEASES_ENABLED` | `1` | Kill switch for background extraction: `0` stops new lease assignments |
| `EXTRACT_TASK_LEASE_PAGE_SIZE` | `256` | Most features in one lease |
| `EXTRACT_TASK_LEASE_BLOCK_SIZE` | `256` | Features whose geometries are loaded together |
| `EXTRACT_TASK_LEASE_SECONDS` | `1800` | How long a lease is held before it can be taken over |
| `EXTRACT_TASK_LEASE_SCAN_WINDOW` | `100000` | Feature ids one scan looks through |
| `EXTRACT_TASK_LEASE_BISECT_ATTEMPT` | `3` | Failed attempts before a page is split in half |
| `EXTRACT_TASK_LEASE_READ_REPLICA` | `0` | Read lease inputs from a standby (needs `PG_RO_*` on the workers) |
| `EXTRACT_TASK_LEASE_REPLICA_WAIT_SECONDS` | `2.0` | How long to wait for the standby to catch up |
| `EXTRACT_COVERAGE_CHUNK_SIZE` | `5000` | Features per coverage chunk |
| `EXTRACT_RESET_CHUNK_SIZE` | `5000` | Rows per sync reset chunk |
| `EXTRACT_SYNC_INTERVAL_SECONDS` | `60` | How often beat runs sync |
| `EXTRACT_SYNC_CHUNKS_PER_RUN` | `20` | Chunks of work one sync run does |

[Extraction Workflow](extraction-workflow.md) explains the lease terms.

## Stats and status

| Variable | Default | Purpose |
|---|---|---|
| `STATS_REPORT_INTERVAL_SECONDS` | `3600` | How often the stats snapshot is rebuilt. `0` stops rebuilding; the last snapshot is still served |
| `STATUS_BACKLOG_MINUTES` | `180` | How long the oldest unfinished request may wait before the status says "backlogged" |

## Rate limits

| Variable | Default | Applies to |
|---|---|---|
| `THROTTLE_RATE_REQUEST_SUBMIT` | `60/hour` | Submitting requests |
| `THROTTLE_RATE_REQUEST_TOKEN` | `10/hour` | Emailed request-history links |
| `THROTTLE_RATE_SHARE_CREATE` | `120/hour` | Creating share links |
| `THROTTLE_RATE_PUBLIC_API_ANON` | `100/hour` | The public API, per address |
| `THROTTLE_RATE_STAC_API_ANON` | `100/hour` | The STAC API, per address |

## MCP server

| Variable | Default | Purpose |
|---|---|---|
| `MCP_BASE_URL` | `http://localhost:8001` | The MCP server's public URL |
| `OIDC_PRIVATE_KEY` | empty | Signing key for GeoQuery's OIDC provider, which the MCP server signs users in through |
| `MCP_OIDC_CLIENT_ID`, `MCP_OIDC_CLIENT_SECRET` | empty | The MCP server's client registration (`ensure_mcp_oidc_client` creates it) |
| `MCP_OIDC_INTERNAL_URL` | `FRONTEND_BASE_URL` | Where the MCP server reaches the backend for back-channel OIDC calls; the backend Service in the cluster |
| `MCP_JWT_SIGNING_KEY` | empty | Keep it stable, so MCP client registrations survive secret rotation |
| `MCP_AUTH_DISABLED` | `False` | Turn sign-in off (tests and local work only) |
| `MCP_ACCESS_TOKEN_EXPIRY_SECONDS` | 30 days | MCP access token lifetime |
| `MCP_STATE_POOL_SIZE` | `4` | Database connections for OAuth state |
| `MCP_RESULTS_MAX_ROWS`, `MCP_RESULTS_MAX_COLUMNS`, `MCP_RESULTS_CSV_MAX_BYTES`, `MCP_MODEL_CONTENT_MAX_BYTES` | `200`, `25`, 5 MB, 512 KB | Caps on data returned to a model |
| `MCP_MAP_MAX_FEATURES`, `MCP_MAP_MAX_BYTES` | `5000`, 3 MB | Caps on the map app |
| `MCP_SUBMIT_MAX_TASKS` | `250000` | Largest request, in extractions, the MCP server will submit |

## Metrics

| Variable | Default | Purpose |
|---|---|---|
| `PROMETHEUS_ENABLED` | `False` | Django metrics, on `PROMETHEUS_METRICS_PORT` (`9091`) |
| `WORKER_METRICS_PORT` | `0` (off) | The extract worker's exporter. Also needs `PROMETHEUS_MULTIPROC_DIR`, since tasks run in child processes |
