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
  default volume path for dataset data is `/data/datasets/`.
- Unrecognized keys in the JSON are logged and skipped rather than causing a failure, so ingest
  JSONs that have drifted from the current `Dataset` model will still load.
- Each ingest JSON is applied in its own transaction. When a dataset has several, a failure in one
  does not roll back the others — the command logs each failure and exits non-zero at the end.

### Metadata-only updates

To change only a dataset's descriptive metadata -- license, source, citation,
title, tags -- pass `--metadata-only`:

```sh
python manage.py ingest_dataset <dataset-name> --metadata-only
```

This reads no data files, so it needs no data volume mounted, and it leaves
`DatasetResource` rows, mappings, processing options and the derived
spatial/temporal fields untouched. Because nothing coverage or extraction
depends on can change, it also skips the usual post-ingest coverage and
extract dispatch.

It only updates: the dataset must already exist, or the command errors. It
cannot be combined with `--update` or `--update-or-insert`.

The structural fields -- `path`, `type`, `file_extension`, `file_mask` -- are
never written, since changing `path` without rescanning would leave resource
rows pointing at the old location. If the JSON's values differ from the stored
row, each difference is logged as a warning and a full ingest is needed to
apply it.

To backfill several datasets, loop over their names:

```sh
for d in acled ucdp wdpa; do
  python manage.py ingest_dataset "$d" --metadata-only
done
```

## Verifying

Enter any PostGIS pod in your namespace and run `psql -d geoquery`, then check that the datasets
and their processing options were created:

```sql
SELECT name, active, public FROM datasets ORDER BY name;
SELECT dataset_id, short_name, function FROM processing_options ORDER BY dataset_id;
```
