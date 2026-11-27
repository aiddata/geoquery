---
description: "Developer documentation for GeoQuery: running it locally, how it works, configuration and command reference, and operating it in production."
---

# Developer documentation

Everything needed to develop, deploy and operate GeoQuery. The code is at [github.com/aiddata/geoquery](https://github.com/aiddata/geoquery): a SvelteKit frontend in `frontend/` and a Django backend in `backend/`, sharing a PostgreSQL + PostGIS database.

New to the codebase? Read [Architecture](architecture.md), then [Local development](development.md).

## Getting started

- [Local development](development.md): running the stack with Docker Compose, configuration, data, and loading a few datasets
- [Testing](testing.md): backend and frontend tests, the type check, and a throwaway test database

## How it works

- [Architecture](architecture.md): the components, the backend apps, how a request flows, storage and access control
- [Request Lifecycle](request-lifecycle.md): request statuses, what moves them, and how to check on one
- [Extraction Workflow](extraction-workflow.md): how extraction work is leased or claimed, computed and committed, and how input changes are reconciled
- [Database](database.md): query, index and tuning decisions, the measurements behind them, and the rules that follow. **Read its working rules before touching `extract_tasks` or `extract_data`.**
- [Background Jobs](background-jobs.md): the extract worker, Celery, and every scheduled job
- [APIs](apis.md): internal endpoints, authentication, the public, STAC and stats APIs, and the MCP server
- [Frontend](frontend.md): routes, the stores that hold a request, tab state, recipes and share links

## Reference

- [Configuration](configuration.md): every environment variable the backend reads
- [Management commands](management-commands.md): the project's own commands, by job

## Production

- [Overview](deploying/kubernetes/index.md): what runs where, and the three repositories involved
- [Deploying with Flux](deploying/kubernetes/flux.md): releasing, verifying a release, and recovering one that stalls
- [Container images](deploying/kubernetes/container.md), [Helm chart](deploying/kubernetes/helm-chart.md), [Cluster operations](deploying/kubernetes/development.md), [Ingest data](deploying/kubernetes/ingest-data.md)
- [Monitoring](services/grafana/index.md): metrics, the Grafana dashboard and alerts
- [GitHub deploy token](gh_deploy_setup.md): the secret releases depend on

## Other design documents

Longer design write-ups live at the repository root: `design-system.md` (colours, type, charts and UI conventions), and `pair-cursor-leases-design.md` with `new-extract-task-system-plan.md` (the design history of background extraction; [Extraction Workflow](extraction-workflow.md) describes what was built).

## Working with AI coding agents

`AGENTS.md` at the repository root, and `frontend/AGENTS.md`, give coding agents the project's rules: how to run things, and that committing, pushing and deploying each need explicit permission. Keep them in step with these pages.
