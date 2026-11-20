---
description: "GeoQuery's background work: the extract worker, the Celery background worker, every scheduled beat job, and the tasks dispatched on demand."
---

# Background jobs

Two kinds of process do GeoQuery's background work:

- **The extract worker** (`manage.py run_extract_worker`) computes extracts. It isn't a Celery worker: each slot claims its work straight from PostgreSQL in a loop. See [Extraction Workflow](extraction-workflow.md).
- **The Celery background worker** (`celery -A geoquery worker -Q background`) runs everything else, from tasks queued on demand and from the beat schedule below. Every Celery task goes to the `background` queue.

## The extract worker's loop

Each slot, in order, takes the first of these it finds:

1. **Pending task rows** (requests, retries, tasks sync reset), claimed in a chunk of `EXTRACT_TASK_CLAIM_BATCH`.
2. **A coverage chunk** for a non-global dataset whose coverage watermark is behind.
3. **A lease page** of background extraction.
4. Otherwise, a jittered wait of about `EXTRACT_WORKER_IDLE_SECONDS`.

On SIGTERM a slot finishes its current task, saves what it computed, hands back the rest, and exits. In the cluster the fleet is autoscaled on `extract_work_demand()`.

## Scheduled jobs (beat)

Defined in `CELERY_BEAT_SCHEDULE` in `settings.py`. Times are UTC.

| Entry | Task | When | What it does |
|---|---|---|---|
| `sync-extract-work` | `analytics.tasks.maintenance.sync_extract_work` | every `EXTRACT_SYNC_INTERVAL_SECONDS` (60 s) | Reconciles input changes recorded by triggers: creates and retires pairs, resets invalid work, publishes rewinds. Database writes wake it sooner |
| `process-user-requests` | `analytics.tasks.maintenance.process_user_requests` | every 5 minutes (:02, :07, …) | The request sweep: finishes requests whose tasks are done, builds their output and emails them |
| `free-stale-processing-tasks` | `analytics.tasks.maintenance.free_stale_processing_tasks` | every 10 minutes | Returns task rows stuck running longer than `STALE_TASK_MINUTES` to pending |
| `manage-processing-task-errors` | `analytics.tasks.maintenance.manage_processing_task_errors` | every 10 minutes, 5 past | Returns failed task rows to pending, up to `MAX_EXTRACT_TASK_ATTEMPTS` |
| `reset-stale-requests` | `analytics.tasks.maintenance.reset_stale_requests` | hourly | Recovers requests stranded by a crashed sweep or never materialized, and cleans up output directories they left |
| `build-stats-report` | `analytics.tasks.maintenance.build_stats_report` | every `STATS_REPORT_INTERVAL_SECONDS` (1 hour) | Rebuilds the stats snapshot behind `/stats` and the stats API |
| `ensure-dataset-partitions` | `datasets.tasks.ensure_all_dataset_partitions_task` | daily, 01:30 | Creates any missing per-dataset partitions |
| `celery-backend-cleanup` | `celery.backend_cleanup` | daily, 04:00 | Deletes expired task results ([Database §9](database.md#9-celery-result-backend)) |
| `build-data-docs` | `datasets.tasks.build_data_docs_task` | daily, 05:00 | Writes the dataset and boundary docs bundle the docs site downloads |
| `run-user-outreach` | `analytics.tasks.maintenance.run_user_outreach` | Tuesdays, 06:00 | Emails the team a list of users who may welcome a follow-up |
| `sweep-export-gists` | `visualize.tasks.sweep_export_gists` | hourly | Deletes notebook-export gists older than `EXPORT_GIST_TTL_SECONDS` |
| `purge-mcp-oauth-state` | `mcp_server.tasks.purge_expired_oauth_state` | hourly | Deletes expired MCP OAuth state |

The sweeps that touch `extract_tasks` are offset from each other so they never share a tick; `settings.py` records why each runs as often as it does.

## Tasks queued on demand

| Task | Queued by |
|---|---|
| `materialize_request_tasks` | Submitting a request: creates its task rows and moves it to queued |
| `process_user_requests` | A request becoming queued, so the sweep looks at it straight away rather than at its next tick |
| `ingest_custom_boundary_task` | Submitting a request with an uploaded boundary file (beta) |
| `ensure_dataset_partitions` | Creating a dataset (on commit) |
| `sync_extract_work` | Changes to extraction inputs, so sync runs before its next beat tick |

## Adding a job

- Put the task in the app that owns the behaviour. A new module under `analytics/tasks/` must be star-imported in `analytics/tasks/__init__.py`, or workers drop its messages ([Database §0](database.md#0-working-rules)).
- Add a reaper for any "in progress" state it writes ([Database §8](database.md#8-every-claim-marker-needs-a-reaper)).
- If it reads `extract_tasks` or `extract_data`, filter by `dataset_id` ([Database §1](database.md#1-partitioned-tables-every-query-must-name-dataset_id)).
- Set `ignore_result=True` if it runs often, and `expires` on its beat entry if a late run is worthless.
- Restart `worker-background` and `beat` locally after changing task code; they don't reload.
