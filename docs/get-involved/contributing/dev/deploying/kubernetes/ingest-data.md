---
description: "Loading datasets and boundary sets into GeoQuery with the ingest commands, updating metadata, and what happens after an ingest."
---

# Ingest data

Datasets and boundary sets are loaded with management commands. In production, run them in the `geoquery-import` pod, which has the data volume mounted at `/data` ([Cluster operations](development.md#running-management-commands)); locally, in the `backend` container, with the files under `./data`.

```sh
kubectl -n geoquery-prod exec -it deploy/geoquery-import -- bash
cd /app/backend
```

The files themselves are prepared by the [geo-datasets](https://github.com/aiddata/geo-datasets) pipelines, which also hold each dataset's ingest JSON.

## Adding datasets

```sh
uv run manage.py ingest_dataset <dataset-name>
```

Given a bare name (e.g. `esa_landcover`), the command resolves every ingest JSON under that
dataset's directory in the [geo-datasets repository](https://github.com/aiddata/geo-datasets/tree/master/datasets),
recursing into subdirectories, and ingests each one in turn. You can also pass a local path or a
raw GitHub URL to ingest a single JSON:

```sh
uv run manage.py ingest_dataset /data/esa_landcover.json
uv run manage.py ingest_dataset https://raw.githubusercontent.com/aiddata/geo-datasets/master/datasets/gpm/yearly_raster_ingest.json
```

Use `--edit` to open `$EDITOR` and compose the ingest JSON interactively.

### Notes

- The `path` field in the ingest JSON must be the absolute path **inside the container**, under
  `/data`.
- Unrecognized keys in the JSON are logged and skipped rather than causing a failure, so ingest
  JSONs that have drifted from the current `Dataset` model will still load.
- Each ingest JSON is applied in its own transaction. When a dataset has several, a failure in one
  does not roll back the others — the command logs each failure and exits non-zero at the end.

### Metadata-only updates

To change only a dataset's descriptive metadata -- license, source, citation,
title, tags -- pass `--metadata-only`:

```sh
uv run manage.py ingest_dataset <dataset-name> --metadata-only
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
  uv run manage.py ingest_dataset "$d" --metadata-only
done
```

To change only processing option descriptions (the text beside each measure), use
`update_measure_descriptions`, which starts no extraction either.

## Adding boundary sets

| Command | Ingests |
|---|---|
| `ingest_geoboundaries` | geoBoundaries sets from files under `--data-dir` (default `/data/boundaries/geoboundaries/`), for the release `--commit` (default `57dcd43`). `--iso3 GHA AFG` limits it to some countries |
| `ingest_boundary <path\|url>` | Any boundary set described by a `boundary_ingest.json` |
| `ingest_tiger` | US Census TIGER boundaries, from `--path` (default `/data/boundaries/tiger/ingest_2025_county.json`) |

New collections are inactive and private unless you pass `--active` and `--public` (or change them in the Django admin later). The useful options they share:

- `--skip-existing` leaves collections that already exist alone.
- `--reload-geometry` wipes and re-ingests an existing collection's features; without it, only its metadata is updated.
- `--no-refresh-views` (or `--refresh-views` for `ingest_geoboundaries`) controls whether the simplified-geometry tables used for map tiles are updated as it goes. If they aren't, run `rebuild_simplified_geometries` afterwards, and `rebuild_cluster_points` for the map's clusters.

## What happens next

Nothing else needs running. Database triggers record each new or changed dataset, resource, processing option and collection, and sync on the background workers works out what to extract ([Extraction Workflow](../../extraction-workflow.md)). A new dataset gets its own `extract_tasks` / `extract_data` partitions automatically. `extract_work_status` shows the work queued for it.

If you change files on disk without going through an ingest, for example replacing a raster in place, tell GeoQuery with `invalidate_extract_inputs`, so stored results are recomputed.

## Verifying

Enter any PostGIS pod in your namespace and run `psql -d geoquery`, then check that the datasets
and their processing options were created:

```sql
SELECT name, active, public FROM datasets ORDER BY name;
SELECT dataset_id, short_name, function FROM processing_options ORDER BY dataset_id;
```
