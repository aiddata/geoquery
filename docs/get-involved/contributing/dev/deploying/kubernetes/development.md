---
description: "Day-to-day commands against GeoQuery's production cluster: looking at pods and logs, running management commands, reaching the database, pausing extraction, and checking what's deployed."
---

# Cluster operations

Commands for working with the production deployment. They assume `kubectl` is pointed at the cluster, and most are read-only. Anything that writes to production (a management command that changes data, a scale, a patch) should be agreed with the team first.

Workloads run in the `geoquery-prod` namespace; the `HelmRelease` that manages them is in `aiddata` ([Production overview](index.md)).

## Looking around

```bash
kubectl -n geoquery-prod get pods
kubectl -n geoquery-prod logs deploy/geoquery-backend --since=30m
kubectl -n geoquery-prod logs deploy/processing-worker --since=10m --prefix
kubectl -n geoquery-prod rollout status deploy/geoquery-backend
```

A terminal UI such as k9s or sofka makes this quicker, and some include Flux actions (reconcile, suspend, resume) for `HelmRelease` and `HelmRepository` objects.

## Running management commands

Use the `geoquery-import` pod: it has the backend image, the data and requests volumes, and database access, and serves no traffic.

```bash
kubectl -n geoquery-prod exec -it deploy/geoquery-import -- bash
cd /app/backend
uv run manage.py extract_work_status
```

[Management commands](../../management-commands.md) lists what's available. Prefer commands that report (`extract_work_status`, `manage_user_requests --dry-run`) before ones that change anything.

## The database

The database is a CloudNativePG cluster, `geoquery-db`. With the [cnpg kubectl plugin](https://cloudnative-pg.io/documentation/current/kubectl-plugin/):

```bash
kubectl cnpg status geoquery-db -n geoquery-prod     # instances, replication, backups
kubectl cnpg psql geoquery-db -n geoquery-prod -- -d geoquery
```

Without the plugin, `kubectl exec` into the primary pod and run `psql -d geoquery`. Connect to a replica for heavy reads. Read [Database](../../database.md) before querying `extract_tasks` or `extract_data`: always filter on `dataset_id`.

## Extraction

- **Health:** `uv run manage.py extract_work_status` in the import pod, and the Grafana dashboard.
- **Pausing:** set `tasks.processing.paused` in the environment overlay to stop the processing workers, or set `EXTRACT_TASK_LEASES_ENABLED=0` to stop only background extraction while requests carry on.
- **Capacity:** KEDA scales `processing-worker` on outstanding demand, within the bounds in the chart's `tasks.processing` values. Change the bounds in the overlay, not by scaling the Deployment.

## What's deployed

```bash
# chart version Flux last applied, and its status
kubectl get helmrelease geoquery-prod -n aiddata \
  -o jsonpath='{.status.lastAttemptedRevision}{"\n"}'

# image tags (commit SHAs) actually running
kubectl -n geoquery-prod get deploy geoquery-backend geoquery-frontend \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}'
```

From outside the cluster, the frontend's build id is at `https://geoquery.aiddata.wm.edu/_app/version.json`; it changes when a new frontend image is live. [Deploying with Flux](flux.md) covers releases that stall.
