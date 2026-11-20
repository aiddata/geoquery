---
description: "The geoquery Helm chart in aiddata/helm-charts: what it deploys, its main values, how environments override them, and how to change it."
---

# Helm chart

The chart lives in [`aiddata/helm-charts`](https://github.com/aiddata/helm-charts) at `charts/geoquery/`, not in this repository. It's published to `https://aiddata.github.io/helm-charts` by that repository's `Release Charts` workflow, and Flux installs it from there.

You rarely edit `Chart.yaml` or the image tags yourself: a release commits the new chart version and image tags for you ([Deploying with Flux](flux.md)).

## What it deploys

| Template folder | Contents |
|---|---|
| `frontend/` | The frontend Deployment and Service, and an Ingress or Gateway API `HTTPRoute`, depending on `exposure.type` |
| `backend/` | The backend Deployment (uvicorn) and Service, and the idle `geoquery-import` Deployment for management commands |
| `mcp/` | The MCP server Deployment, Service and disruption budget |
| `proxy/` | nginx, with its routing in a ConfigMap: `/api` to the backend, `/mcp` and the OAuth paths to the MCP server, everything else to the frontend |
| `tasks/` | Processing workers (the extract worker) with a KEDA `ScaledObject`, background workers, Celery beat, and a RabbitMQ cluster |
| `database/` | The CloudNativePG `Cluster`, its pgBouncer `Pooler`s (read/write, read-only, and per-workload pools), scheduled backups to object storage, custom monitoring queries, and the pre-upgrade migration Job |
| `volumes/` | NFS-backed volumes for `/data` and `/requests` |
| `networkpolicies/` | One policy per workload: each may only talk to what it needs |
| `metrics/` | PodMonitors for every component, a `PrometheusRule` of alerts, and the Grafana dashboard as a ConfigMap (`dashboards/` holds its JSON) |

## Main values

`values.yaml` documents every value inline. The top-level groups:

| Key | Covers |
|---|---|
| `frontend`, `backend`, `mcp` | Images (the release sets the tags), replicas, resources |
| `proxy`, `exposure` | nginx, and how the site is exposed (`ingress`, `gateway` or `none`) |
| `networkPolicies` | Whether policies are rendered, and what may reach the site |
| `tasks.processing` | Extract worker replicas, `concurrency` (slots per pod), `claimBatch`, `paused`, drain and grace periods, and autoscaling bounds |
| `tasks.background` | Celery worker replicas and concurrency |
| `rabbitmq` | The broker |
| `django` | Secret key, debug, allowed hosts, CSRF origins, base URL |
| `geoquery` | Application settings, and the Kubernetes Secrets holding each credential (email, GitHub OAuth, gist token, OIDC key) |
| `volumes` | The NFS shares for data and requests |
| `database` | Instances, storage, PostgreSQL parameters, pooler sizes, backups and recovery |
| `protomaps` | The basemap key's Secret |
| `metrics` | The master switch for everything under `metrics/` |

Values become the environment variables described in [Configuration](../../configuration.md).

## Environments

Each environment's settings are a Kustomize overlay in `aiddata/nova-fluxcd` (`geoquery/app/overlays/<env>/`), patching the `HelmRelease`: the chart version to install, and the values that differ from the chart's defaults, such as host names, Secrets, NFS shares, storage sizes and database parameters.

Two rules learned the hard way ([Database §10](../../database.md#10-cluster-settings-and-storage)):

- **Declare database storage size in the overlay**, not just the storage class. A replacement instance is created at the spec's size, not the size the live volumes have grown to.
- **Production overrides `max_wal_size` to 16 GB.** The chart default is too small for its write volume.

## Changing the chart

1. Edit `charts/geoquery/` in `aiddata/helm-charts` and merge it. Leave `version:` alone; nothing is published or deployed yet.
2. Release from this repository with a `[DEPLOY-X.Y.Z]` marker. The deploy workflow bumps `version:` and the image tags, which publishes a chart that includes your change.

To check a template change before merging, render it locally:

```bash
helm template geoquery charts/geoquery -f my-values.yaml | less
```

Settings that can be reloaded without a restart can be tried by patching the live resource first, since Flux doesn't revert drift until the next upgrade ([Deploying with Flux](flux.md#experimental-changes-to-cluster-settings)).
