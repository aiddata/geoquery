# Ingest Data

This guide walks through ingesting dataset and boundary data using the GeoQuery backend on Kubernetes.

## Adding Datasets

Datasets are ingested with the `ingest_dataset` management command, run from a backend pod in your namespace:

```sh
python manage.py ingest_dataset <dataset-name>
```

Given a bare name (e.g. `esa_landcover`), the command resolves every ingest JSON under that
dataset's directory in the [geo-datasets repository](https://github.com/aiddata/geo-datasets/tree/master/datasets),
recursing into subdirectories, and ingests each one in turn. You can also pass a local path or a
raw GitHub URL to ingest a single JSON:

```sh
python manage.py ingest_dataset /data/esa_landcover.json
python manage.py ingest_dataset https://raw.githubusercontent.com/aiddata/geo-datasets/master/datasets/gpm/yearly_raster_ingest.json
```

Use `--edit` to open `$EDITOR` and compose the ingest JSON interactively.

### Notes

- The `path` field in the ingest JSON must be the absolute path **inside the container**. The
  default volume path for raster data is `/data/rasters/`.
- Unrecognized keys in the JSON are logged and skipped rather than causing a failure, so ingest
  JSONs that have drifted from the current `Dataset` model will still load.
- Each ingest JSON is applied in its own transaction. When a dataset has several, a failure in one
  does not roll back the others — the command logs each failure and exits non-zero at the end.

## Verifying

Enter any PostGIS pod in your namespace and run `psql -d geoquery`, then check that the datasets
and their processing options were created:

```sql
SELECT name, active, public FROM datasets ORDER BY name;
SELECT dataset_id, short_name, function FROM processing_options ORDER BY dataset_id;
```
