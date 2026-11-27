---
description: "Viewing GeoQuery's Grafana dashboard in the cluster, and working with metrics locally."
---

# Viewing the dashboard

## In the cluster

The dashboard appears in the cluster's Grafana as **GeoQuery (geoquery-prod)** once `metrics.enabled` and `metrics.grafanaDashboard` are on in the environment's values ([Monitoring](index.md)). If Grafana isn't exposed, port-forward its Service:

```bash
kubectl -n monitoring port-forward svc/<grafana-service> 3000:80
```

then open http://localhost:3000. The namespace and Service name depend on how the monitoring stack was installed.

## Locally

The Compose stack doesn't run Prometheus or Grafana. To look at metrics while developing:

- **Extract worker:** set `WORKER_METRICS_PORT` and `PROMETHEUS_MULTIPROC_DIR` (Compose already sets the latter for `worker-processing`), publish the port, and read `http://localhost:<port>/metrics`.
- **Backend:** set `PROMETHEUS_ENABLED=True`; Django's metrics are then served on `PROMETHEUS_METRICS_PORT` (9091).

For a dashboard, run Prometheus and Grafana yourself (for example from their official images), point Prometheus at those endpoints, and import `dashboards/geoquery.json` from the chart.
