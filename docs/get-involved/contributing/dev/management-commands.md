---
description: "GeoQuery's own Django management commands, grouped by job: running services, loading data, checking and recovering extraction, requests, accounts, and the MCP server."
---

# Management commands

Run them inside a backend container. Locally:

```bash
docker compose exec backend uv run python manage.py <command> --help
```

In the cluster, use the long-running `geoquery-import` pod, which has the backend image and the data volume, rather than a serving pod ([Cluster operations](deploying/kubernetes/development.md)). Each command's `--help`, and its module docstring, say more than this page.

## Running services

| Command | Runs |
|---|---|
| `run_extract_worker` | The extract worker, until SIGTERM or SIGINT. `--concurrency` slots, each in its own process |
| `run_mcp` | The MCP server (streamable HTTP) |
| `migrate` | Django's `migrate`, preceded by `adopt_auth_user` (a no-op unless the database still has the legacy user table). It shadows the built-in, so every caller gets it |

## Loading and updating data

| Command | Does |
|---|---|
| `ingest_dataset <name\|path\|url>` | Ingests a dataset from its ingest JSON. A bare name resolves every ingest JSON for it in the geo-datasets repository. `--metadata-only` updates descriptive fields alone ([Ingest data](deploying/kubernetes/ingest-data.md)) |
| `update_measure_descriptions` | Updates processing option descriptions from geo-datasets; starts no extraction |
| `ingest_geoboundaries` | Ingests geoBoundaries sets, optionally for chosen countries (`--iso3`) |
| `ingest_boundary <path\|url>` | Ingests any boundary set from a `boundary_ingest.json` |
| `ingest_tiger` | Ingests US Census TIGER boundaries |
| `rebuild_simplified_geometries` | Rebuilds the simplified geometries used for map tiles, one collection at a time |
| `rebuild_cluster_points` | Rebuilds every collection's map clusters |
| `ensure_dataset_partitions` | Creates missing per-dataset `extract_tasks` / `extract_data` partitions. Idempotent |
| `build_data_docs` | Builds the dataset and boundary docs: with `--out <dir>` into a folder for a local preview, otherwise the bundle the docs site downloads |

## Extraction: checking and recovering

| Command | Does |
|---|---|
| `extract_work_status` | Reports extraction health: dirty input scopes, leases, pair errors and outstanding demand. Start here |
| `initialize_extract_work` | Initializes datasets still waiting to bootstrap for pair cursor leases. Idempotent |
| `invalidate_extract_inputs` | Records that a dataset's or collection's inputs changed outside the database (for example a raster replaced on disk), so its results and coverage are reset and recomputed |
| `rewind_pair_cursors` | Rewinds pair cursors and coverage watermarks so features are scanned again, as a durable rewind that sync applies |
| `free_stale_processing_tasks` | Returns task rows stuck running to pending (also scheduled) |
| `manage_processing_task_errors` | Returns failed task rows to pending, up to `MAX_EXTRACT_TASK_ATTEMPTS` (also scheduled) |

[Extraction Workflow](extraction-workflow.md) explains scopes, leases and rewinds.

## Requests

| Command | Does |
|---|---|
| `manage_user_requests` | The request sweep (also scheduled). `--id` for one request, `--dry-run` to see what it would do |
| `reset_stale_requests` | Recovers requests stranded by a crashed sweep or never materialized (also scheduled) |
| `reset_errored_requests` | Returns requests in error to queued, to try again |
| `import_legacy_requests` | Imports completed requests from the previous GeoQuery out of a Parquet export. Safe to re-run |
| `generate_stats` | Writes an HTML report of request history |
| `run_user_outreach` | Emails the team users who may welcome a follow-up (also scheduled) |

[Request Lifecycle](request-lifecycle.md) covers when to use the recovery commands.

## Accounts

| Command | Does |
|---|---|
| `adopt_auth_user` | Adopts a legacy `auth_user` table as `accounts.User`, so `migrate` can run. Safe to re-run |
| `adopt_legacy_users` | Creates verified email addresses for pre-allauth users, so they can sign in. Safe to re-run |
| `backfill_request_claims` | Attaches unclaimed past requests to accounts by matching contact emails against verified addresses. Safe to re-run |

## MCP server

| Command | Does |
|---|---|
| `ensure_mcp_oidc_client` | Creates or updates the MCP server's OIDC client registration. Idempotent; the deploy's migration Job runs it |
| `report_missing_attribution` | Lists active datasets and boundary sets with no license or citation recorded |
