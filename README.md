# geoquery-update

Development of source code for an updated version of [GeoQuery](https://geoquery.org)

The database [schema](schema.aml) can be loaded using the free web based databse exploration tool [Azimutt](https://azimutt.app/).



To start postgis:
`podman run --name geoquery-postgis -p 5432:5432 -e POSTGRES_PASSWORD=mysecretpassword -d docker.io/postgis/postgis:16-3.4-alpine`

To get postgis container ID:
`podman ps`

Then to stop/start/restart (replace restart with desired command):
`podman restart <ID>`

To init db (overwrite is optional):
`python src/init_db.py --overwrite`

To add feature data:
`python prepare_gB.py`

To add datasets:
`python ingest_dataset.py`

To build coverage checks between features and datasets:
`python build_coverage_records.py`

To create extract tasks:
`python build_extract_tasks.py`
