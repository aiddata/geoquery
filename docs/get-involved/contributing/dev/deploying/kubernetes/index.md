---
description: "How GeoQuery runs in production: Kubernetes on W&M's research cluster, deployed by a Helm chart that Flux reconciles, and what runs where."
---

# Production overview

Production runs on Kubernetes, on William & Mary's research computing cluster. Kubernetes lets GeoQuery be stood up the same way on any cluster, gives it standard building blocks (Deployments, Jobs, Services, network policies, autoscaling), and fits where W&M research computing is heading.

Nothing is deployed by hand. The application is packaged as a Helm chart, and FluxCD keeps the cluster matching the chart version pinned in a GitOps repository. Releasing means merging a commit with a `[DEPLOY-X.Y.Z]` marker ([Deploying with Flux](flux.md)).

## The three repositories

| Repository | Holds |
|---|---|
| `aiddata/geoquery` | The application, its Containerfiles, and the workflows that build images and start a release |
| `aiddata/helm-charts` | The `geoquery` chart (`charts/geoquery/`), published to `https://aiddata.github.io/helm-charts` ([Helm chart](helm-chart.md)) |
| `aiddata/nova-fluxcd` | The cluster's Flux configuration: the `HelmRelease` and each environment's overlay pinning a chart version (`geoquery/app/overlays/<env>/`) |

## What runs where

The `HelmRelease` is `geoquery-prod` in the `aiddata` namespace; the workloads it creates run in `geoquery-prod`.

| Workload | Runs |
|---|---|
| `geoquery-frontend` | The SvelteKit server |
| `geoquery-backend` | Django under uvicorn |
| `geoquery-mcp` | The MCP server |
| `geoquery-proxy` | nginx: routes `/api` to the backend, MCP and OAuth paths to the MCP server, the rest to the frontend |
| `processing-worker` | The extract worker, autoscaled by KEDA on `extract_work_demand()` and claim contention |
| `background-worker` | Celery on the `background` queue |
| `celery-beat` | The schedule ([Background jobs](../../background-jobs.md)) |
| `geoquery-rabbitmq` | Celery's broker (a RabbitMQ operator cluster) |
| `geoquery-db` | A CloudNativePG cluster (PostgreSQL 17 + PostGIS) with standbys, behind read/write and read-only pgBouncer poolers, and scheduled backups to object storage |
| `geoquery-import` | An idle pod with the backend image and data volume, for running management commands |
| migration Job | A Helm pre-upgrade hook: `migrate`, `createcachetable`, `ensure_mcp_oidc_client` |

Input data and request outputs are on NFS volumes, mounted at `/data` and `/requests`. Prometheus scrapes the backend, workers, database and RabbitMQ, and the chart ships a Grafana dashboard and alert rules ([Monitoring](../../services/grafana/index.md)).

## Pages in this section

- [Deploying with Flux](flux.md): releasing, verifying a release, and what to do when one stalls.
- [Container images](container.md): how the images are built and tagged.
- [Helm chart](helm-chart.md): what the chart contains and how to change it.
- [Cluster operations](development.md): day-to-day commands against the cluster.
- [Ingest data](ingest-data.md): loading datasets and boundaries.
- [GitHub deploy token](../../gh_deploy_setup.md): the token the release workflow needs.
