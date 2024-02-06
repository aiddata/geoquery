# Local Deployment

This guide is for running gqcore directly on your machine, using a PostgreSQL instance hosted from within a container.
`podman` is used in these examples, but they should work similarly for `docker` as well.

!!! warning

    While these instructions may still work, the most recent development has
    been focused on Kubernetes. This guide may be out-of-date.

## Install gqcore

To install base geoquery files as package (run from repo root):
`pip install -e .`

!!! note

    Consider installing this package inside of a conda environment to help
    prevent version conflicts on your system.

## Start a PostgreSQL server

To start PostgreSQL with PostGIS:
```
podman run --name geoquery-postgis -p 5432:5432 -e POSTGRES_PASSWORD=mysecretpassword -d docker.io/postgis/postgis:16-3.4-alpine
```

To get postgis container ID, run `podman ps`

Then to stop/start/restart (replace restart with desired command):
`podman restart <ID>`

To initialize the database (`--overwrite` is optional):
```
python src/gqcore/utils/db/init/init_pg_tables.py --overwrite
python src/gqcore/utils/db/init/init_pg_views.py --overwrite
```

## Ingest data

To add feature data:
```
python ingest/features/prepare_gB.py
```

To add datasets:
```
python ingest/datasets/{ingest_dataset.py}
```

## Build coverage checks

To build coverage checks between features and datasets:
```
python src/gqcore/tasks/build_coverage_records.py
```

## Create and process extract tasks

To create extract tasks:
```
python src/gqcore/tasks/build_extract_tasks.py
```

To process extract tasks:
```
python src/gqcore/tasks/process_extract_tasks.py
```

## Setup grafana

See the grafana documentation page for information on setting up grafana and other logging utilities

