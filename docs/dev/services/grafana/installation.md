# Installing Grafana

## Kubernetes

The helm chart in this repository automatically installs Grafana, so no further steps are required.
Follow the installation instructions for Kubernetes and the Grafana service will become available on the cluster.

See the post-installation instructions for the helm chart for the best way to access Grafana from your machine.

## Locally (podman)

!!! warning

    This guide will get you a working grafana installation, but it is no longer 
    the recommended way to install grafana. Using the helm chart will do all of
    this automatically. If you follow this guide, it will take some tweaking to
    get the various data sources running and connected.

Here's how to get Grafana up-and-running locally with podman, alongside our usual PostgreSQL server so that they can talk to each other

1. Remove the current PostgreSQL container, if it exists
2. **cd to this directory**
3. Create a pod for our two servers with `podman pod create -p 3000:3000 -p 5432:5432 geoquery`
   This will expose port 3000 for Grafana and 5432 for PostgreSQL to your local machine
4. Add the PostgreSQL container to your pod with `podman run --pod geoquery -e POSTGRES_PASSWORD=mysecretpassword -d docker.io/postgis/postgis:16-3.4-alpine`
5. Add the Grafana container to your pod with `podman run -d --pod geoquery grafana/grafana-oss`
6. Create `loki-config.yaml` using the YAML below
7. Add the Loki container to your pod with `podman run -d --pod geoquery -v ./loki-config.yaml:/etc/loki/local-config.yaml:Z grafana/loki:latest`
8. Create `promtail-config.yaml` using the YAML below
9. Add the promtail container to your pod with `podman run -d --pod geoquery -v ../logs:/var/log:Z -v ./promtail-config.yaml:/etc/promtail/config.yml:Z grafana/promtail:latest`
   **change `../logs` above to point to the logs directory you specified in `config.toml`**
10. Re-initialize the PostgreSQL server using the usual instructions at the root of this repo
11. Navigate to http://localhost:3000 in your browser, and login with username admin, password admin
12. Click on Add a Data Source, and scroll down to PostgreSQL. Here are the connection options for PostgreSQL:
    - Host: localhost:5432
    - Database: postgres
    - User: postgres
    - User: postgres Password: mysecretpassword
    - TLS/SSL Mode: disable

    At the bottom of the page, click Save and Test
13. Add another Data Source: Loki
    - Connection URL: http://localhost:3100

    At the bottom of the page, click Save and Test
14. Save and test the PostgreSQL connection, making sure it is successful
15. Go back home, and click on New Dashboard
16. Click on Import dashboard
17. Paste in the JSON found in `dashboard.json` in this directory
18. Open the new dashboard and see it in action! If everything went well it should look like the screenshot above

**loki-config.yaml**
```yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

limits_config:
  ingestion_rate_strategy: local # Default: global
  max_global_streams_per_user: 5000
  max_query_length: 0h # Default: 721h
  max_query_parallelism: 32 # Old Default: 14
  max_streams_per_user: 0 # Old Default: 10000

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

ruler:
  alertmanager_url: http://localhost:9093
```

**promtail-config.yaml**
```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://localhost:3100/loki/api/v1/push

scrape_configs:
- job_name: system
  pipeline_stages:
  - regex:
      expression: "^(?P<timestamp>.+?) \\| (?P<level>[[:alpha:]]+?) +?\\| (?P<message>.+)"
  - labels:
      level:
  - timestamp:
      source: timestamp
      format: DateTime
  - output:
      source: message
  static_configs:
  - targets:
      - localhost
    labels:
      job: varlogs
      __path__: /var/log/*log
```
