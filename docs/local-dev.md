# Local Development

!!! warning

    While these instructions may still work, the most recent development has
    been focused on Kubernetes. This guide may be out-of-date.

To install base geoquery files as package (run from repo root):
`pip install -e .`

To start postgis:
`podman run --name geoquery-postgis -p 5432:5432 -e POSTGRES_PASSWORD=mysecretpassword -d docker.io/postgis/postgis:16-3.4-alpine`

See the `grafana` directory for information on setting up grafana and other logging utilities

To get postgis container ID:
`podman ps`

Then to stop/start/restart (replace restart with desired command):
`podman restart <ID>`

To init db (overwrite is optional):
`python src/gqcore/tasks/init_pg_tables.py --overwrite`
`python src/gqcore/tasks/init_pg_views.py --overwrite`

To add feature data:
`python ingest/features/prepare_gB.py`

To add datasets:
`python ingest/datasets/{ingest_dataset.py}`

To build coverage checks between features and datasets:
`python src/gqcore/tasks/build_coverage_records.py`

To create extract tasks:
`python src/gqcore/tasks/build_extract_tasks.py`

To process extract tasks:
`python src/gqcore/tasks/process_extract_tasks.py`
