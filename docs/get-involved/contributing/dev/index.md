# Developer Documentation

This section covers everything needed to develop, deploy, and operate GeoQuery.

## Sections

- [Development](development.md) — running the stack locally with Docker Compose
- [Database](database.md) — query, index and tuning decisions, and the rules that follow from them
- [Request Lifecycle](request-lifecycle.md) — request statuses, what moves them, and how to check on one
- [Deploying](deploying/kubernetes/flux.md) — releasing with Flux, and what to do when it stalls
- [Why Kubernetes](deploying/kubernetes/index.md) — background on the deployment target
- [Services](services/grafana/index.md) — monitoring and supporting services

## Building these docs

```
uv run zensical serve
```
