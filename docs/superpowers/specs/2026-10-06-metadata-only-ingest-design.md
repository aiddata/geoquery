# Metadata-only dataset ingest

**Date:** 2026-10-06
**Status:** Approved, pending implementation

## Problem

`Dataset.license` and `Dataset.license_url` are empty for all 56 rows in prod,
and `source_name`/`source_url` are populated for exactly one. The cause was in
the ingest JSONs, not the backend: they carried `sources_web`/`sources_name`,
which are not `Dataset` field names, so `_dataset_fields_from_json` logged them
as unrecognized and dropped them. The one populated row,
`landmarkmap_ipcl_dataset`, is the only dataset whose JSON already used the
singular names.

aiddata/geo-datasets#189 fixed the JSONs: all 95 now carry `license`,
`license_url`, `source_name` and `source_url`. Prod still needs those values.

The existing update paths cannot deliver them. `ingest_dataset --update`
unconditionally calls `_identify_and_create_resources`, which walks the
dataset's path, opens every raster or vector to compute a bounding box,
rewrites `DatasetResource` rows and overwrites the derived spatial and temporal
fields. That requires the data files. The `geoquery-data` PVC is bound but no
running deployment mounts it, so the command fails on a missing path. Even with
the volume mounted, re-scanning every file of every dataset to change two
metadata columns is disproportionate, and it rewrites resources and derived
extents as a side effect.

## Goal

A mode that applies the descriptive metadata an ingest JSON declares, without
reading the data files and without touching anything derived from them.

## Behaviour

`python manage.py ingest_dataset <name> --metadata-only`

Update-only: it errors if the dataset does not exist. A metadata-only insert
would create a row with no resources, which is never useful.

The flag applies to all three input forms the command already accepts: a bare
dataset name resolved against the geo-datasets repo, a local path, or a raw
GitHub URL. A bare name that resolves to several ingest JSONs applies each in
turn, as it does today.

Bulk backfill is a shell loop over dataset names; no `--all` flag.

`--metadata-only` is rejected with `CommandError` if combined with `--update`
or `--update-or-insert`.

### Field partition

Every key appearing across the 95 ingest JSONs falls into one of five groups.

**Applied** — descriptive metadata:

`active`, `public`, `is_global`, `short_name`, `title`, `description`,
`details`, `citation`, `source_name`, `source_url`, `license`, `license_url`,
`tags`, `other`, `ingest_src`, `processing_class`, `variable_factor`,
`variable_description`

`name` is the lookup key and is never written.

`processing_class` and `variable_factor` are plain scalars that do influence
computation — `variable_factor` multiplies extracted values. They are applied
anyway: they are declarative metadata about the dataset, and drift in them is
something an operator would want corrected.

**Excluded, structural** — describe where the data lives:

`path`, `type`, `file_extension`, `file_mask`

Never written. Writing a new `path` while skipping the resource rescan would
leave `DatasetResource` rows pointing at the old location. Each is compared
against the stored row, and any difference is reported as drift with a warning
naming the field, the stored value and the JSON value, and stating that a full
ingest is needed. The metadata update still succeeds.

**Excluded, derived from the data files** — present in the five boundary JSONs:

`spatial_extent`, `temporal_start`, `temporal_end`, `temporal_name`,
`temporal_type`

**Excluded, computation:**

`mappings` and `processing_options` are already in `_NON_MODEL_KEYS`. `mapped`
joins them: `_dataset_fields_from_json` derives it from `mappings`, so writing
it while leaving `Mapping` rows alone would let the flag contradict the rows.

**Already dropped** as non-model keys: `coverage_dependency`, `group_name`,
`group_title`, `group_class`, `group_level`. The `group_*` keys belong to
`FeatureCollection`; `coverage_dependency` was removed from `Dataset` in
migration `0003_remove_dataset_coverage_dependency` but 90 JSONs still carry it.

### Post-ingest hooks

`BaseIngestCommand.execute` fires `trigger_coverage_and_extract.delay()` after
every run. Metadata-only skips it: coverage records and extract tasks depend on
resources and spatial/temporal extent, none of which this mode touches.

A `skip_post_ingest_hooks = False` class attribute on `BaseIngestCommand`,
checked in `execute`, is set by `handle` when the flag is passed. `execute`
calls `super().execute()` — which runs `handle` — before reaching the trigger,
so a flag set inside `handle` is visible. The attribute is generic, so no
dataset concepts leak into the base class and other ingest commands are
unaffected.

## Design

In `backend/datasets/ingest.py`:

```
_load_json(json_data) -> dict
_STRUCTURAL_KEYS  = {"path", "type", "file_extension", "file_mask"}
_DERIVED_KEYS     = {"spatial_extent", "temporal_start", "temporal_end",
                     "temporal_name", "temporal_type"}
_COMPUTATION_KEYS = {"mapped"}

_metadata_update_plan(data, existing) -> (fields, drift)
update_dataset_metadata(json_data) -> Dataset
```

`update_dataset_metadata` is a separate entry point rather than a
`metadata_only` flag on `ingest_dataset`. Threading a bool through
`ingest_dataset` would need conditionals at three separate skip points — the
resource scan, the mappings sync and the processing options loop — inside an
already-long function.

`_load_json` is extracted from `ingest_dataset`'s existing `dict | Path`
handling and shared by both entry points.

`_metadata_update_plan` is pure: it takes the parsed JSON and a plain mapping
of the row's current structural values, and returns the fields to apply plus a
dict of drift. It touches no models and no database. This is deliberate — see
Testing.

`update_dataset_metadata` is a thin `@transaction.atomic` wrapper: load the
JSON, read the existing row's structural values, call the planner, apply with
`Dataset.objects.filter(name=name).update(**fields)`, raise `ValueError` if
zero rows matched, then log the before/after diff for changed fields and warn
on any drift.

In `backend/datasets/management/commands/ingest_dataset.py`: add the
`--metadata-only` argument, validate it against the other update flags, route
`_ingest_path` to `update_dataset_metadata`, and set
`skip_post_ingest_hooks`.

## Testing

Tests go in `backend/datasets/tests/test_ingest.py`.

The `userx` account on the current machine is not in the `docker` group, so
DB-backed tests cannot be run locally. Putting the whole decision logic in a
pure function is what makes the substance of this change testable here.

Runnable locally (`SimpleTestCase`, no database):

- `_metadata_update_plan` applies every field in the Applied group
- it excludes structural, derived and computation keys
- it reports drift when a structural field differs from the stored row
- it reports no drift when structural fields match
- `--metadata-only` combined with `--update` raises `CommandError`

Requires a database (`TestCase`, run in CI or a pod):

- `update_dataset_metadata` updates an existing row's metadata
- it raises when the named dataset does not exist
- it leaves `DatasetResource`, `Mapping` and `ProcessingOption` rows untouched

## Documentation

`docs/get-involved/contributing/dev/deploying/kubernetes/ingest-data.md` gains
a `--metadata-only` section. Its claim that the default raster volume path is
`/data/rasters/` is stale — prod rows and every ingest JSON use
`/data/datasets/` — and is corrected in the same change.

## Out of scope

The boundary side. `FeatureCollection.license` is empty for all 726 rows;
`ingest_geoboundaries.py` sets `"CC BY 4.0"` with spaces where the dataset
JSONs use SPDX `CC-BY-4.0`, and `ingest_tiger.py` sets no license at all.
Tracked separately.

The 39 ingest JSONs with no matching prod row. All 56 prod datasets have a
matching JSON by name; the other 39 are not ingested in prod and need no
update.
