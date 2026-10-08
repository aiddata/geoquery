# Legacy request migration

**Date:** 2026-10-07
**Status:** Approved, pending implementation

## Problem

Requests submitted to the previous version of GeoQuery live only in that
system's MongoDB. Users who submitted them have no way to find them through the
new application: the past-request mechanism reads `analytics.Request`, and
nothing in that table predates the current system.

The old system is still live. A `mongoexport` taken on 2026-10-05 holds 48,675
request documents spanning 2016-10-27 to that same afternoon, 1,874 of them from
2026 alone. So this is a cutover, not an archive import, and the migration has
to run twice: once now against a fixed date, and again when the old system is
retired.

The export itself is already converted to Parquet on this branch by
`request_migration/requests_to_parquet.py`, with
`request_migration/read_requests.py` as the pandas loader. Those two scripts are
the input to this work, not part of it.

## Goal

Legacy requests are findable through the standard past-request mechanisms,
visibly marked as historical, and downloadable. Their individual datasets and
boundaries are **not** mapped onto current catalog entities — the stored names
are shown as text.

## Scope of the import

Of the 48,675 exported documents, 48,666 survive the content filters. How many
a given run actually imports also depends on its `--submitted-before` date; the
figures below are for the whole 2026-10-05 export. The filters:

- `status == 1` (completed). Drops 8 rows: seven at `-2`, one at `-3`.
- `submit_time < --submitted-before`. The operator's fixed date, so each run is
  reproducible and the cutover run picks up exactly the remainder.
- Non-empty contact, boundary, and at least one dataset. Drops 1 row in the
  current export (a request with no datasets). Contact and boundary are
  populated on every completed row today, but the old system is still accepting
  submissions, so these are guards rather than observations.

For reference, the 48,666 rows cover 10,627 distinct contact addresses and
1,297 distinct boundaries.

## Design

### A separate table, not a flag

`LegacyRequest` is its own model with its own table rather than a
`Request.is_legacy` flag. Legacy rows must never reach the completion sweep,
priority bumping, task materialization, `RequestMap`, or the extract workers.
A flag makes that a filter every one of those paths has to remember; a separate
table makes it true by construction. The distinction users see — a flag marking
a request as historical — is then a property of which endpoint served it, not a
column.

Nothing is added to `Request`, and no existing query changes.

### Model

`LegacyRequest` in `analytics/models.py`, table `legacy_requests`:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `CharField(max_length=24)`, pk | Mongo ObjectId hex, preserved |
| `contact` | `CharField(max_length=100)` | legacy email; observed max 57 |
| `custom_name` | `CharField(max_length=100)` | never blank; observed max 96 |
| `submit_time` | `DateTimeField` | |
| `complete_time` | `DateTimeField` | populated on every imported row |
| `boundary_title` | `CharField(max_length=100)` | observed max 73 |
| `boundary_name` | `CharField(max_length=64)` | observed max 39 |
| `boundary_group` | `CharField(max_length=32)` | observed max 25 |
| `dataset_titles` | `ArrayField(CharField(max_length=200))` | display titles, release then raster |
| `dataset_count` | `SmallIntegerField` | up to 252 observed |
| `data` | `JSONField` | `release_data` + `raster_data` verbatim |
| `user` | FK to `AUTH_USER_MODEL`, null, `SET_NULL` | `related_name="legacy_requests"` |
| `imported_at` | `DateTimeField(auto_now=True)` | which run last touched the row |

`Meta.indexes`: `Upper("contact")` and `-submit_time`. A functional index on
`contact` rather than `db_index=True`, because every ownership lookup matches
case-insensitively.

**Why `Upper` and not `Lower`.** Django renders `__iexact` as
`UPPER(x) = UPPER(y)` on PostgreSQL -- hardcoded in the backend's
`lookup_cast`, with no setting to change it -- and an expression index is only
eligible when its expression matches the predicate's exactly. A
`btree(lower(contact))` index therefore cannot serve a `contact__iexact`
lookup. The original design specified `Lower`, mirroring the pre-existing
`requests_contact_lower_idx`, and so inherited its defect: every ownership read
on both tables was sequentially scanning. Migration
`0032_contact_upper_indexes` swaps both tables to `Upper`, which fixes all the
call sites without changing a single query, and the mirroring between
`requests_for_user` and `legacy_requests_for_user` is preserved for free.

This changes nothing users see. An expression index keeps `upper(contact)` only
inside its own B-tree keys; the column is never rewritten and `SELECT contact`
still returns the address as the submitter typed it.

`dataset_titles` takes `custom_name` from each `release_data` entry and `title`
from each `raster_data` entry, release entries first — the two fields the old UI
itself displayed. Observed maxima are 81 and 84 characters. It and
`dataset_count` are denormalized so neither the list nor the detail page parses
the JSON blob; `data` retains full provenance.

### Fields deliberately not imported

- `info` — boilerplate CSV-column help text. 9 distinct values across 48,667
  rows; it is UI copy, not request data.
- `status` — every imported row is completed by definition. The API reports
  `"completed"`. If failed requests are ever wanted, this is one nullable
  column and a changed filter.
- `priority`, `contact_flag`, `comments_requested`, `attempts` — operational
  state of a retired scheduler.
- `prepare_time`, `process_time` — **unreliable.** Of the 48,667 completed
  rows, `prepared` precedes `submitted` in 11,467 and `processed` precedes it
  in 9,963; 8 rows carry an epoch-0 stage time. This is in the source data, not
  an artifact of the Parquet conversion: the old system appears to have written
  `submitted` last.

  **`complete_time` is inverted too, in 9,708 rows (20%)**, and is imported
  anyway because the UI needs *a* completion date and day-granularity display
  hides all but 46 of them. Those 46 — where the inversion crosses a UTC
  calendar date — are suppressed on the detail page rather than rendered as a
  completion preceding a submission. An earlier version of this spec claimed
  submit and complete were "the two that are sound"; that was wrong, and the
  9,716 figure it cited was in fact measuring `complete_time`, not the two
  fields it was offered as evidence against.

### Downloads

Zip files are being copied to the download host under their own directory,
served at `{base}/legacy/{id}.zip`. A `LEGACY_DOWNLOAD_BASE_URL` setting plus a
`legacy_request_links()` in `analytics/services.py`, mirroring the existing
`request_links()`, builds that URL.

The `legacy/` segment lives in the code path, not in the configured base URL,
so it cannot be omitted by a misconfiguration — `LEGACY_DOWNLOAD_BASE_URL`
must therefore not itself end in `/legacy`. Keeping the archive out of the
download host's document root matters because the filenames are not the secret
they appear to be: Mongo ObjectIds are derivable from one another (for a third
of the archive, a known id yields a neighbour's, 27% of the time another
submitter's), so a directory listing at the root would expose all 48,666 at
once. Directory listing should be off for the `legacy/` directory too.

The setting **defaults to `DOWNLOAD_BASE_URL`**, since the archive is served
from the same host. It stays a separate setting so the two can be pointed at
different hosts later without a code change. The fallback is expressed as
`os.environ.get(...) or DOWNLOAD_BASE_URL` rather than a `get()` default,
because compose passes the variable through as an empty string when it is
unset in `.env`, which would otherwise shadow the fallback.

`legacy_request_links()` still returns an empty dict when the resolved base is
empty, so setting both to empty renders no link at all -- but with the shared
default the download button goes live as soon as this deploys. The zips need
to be in place first, or the button 404s.

Zip only. The old system produced no equivalent of the new documentation HTML
or the visualization page, and no `status != 1` row is imported, so there is no
"not ready yet" state to represent.

### Import command

`analytics/management/commands/import_legacy_requests.py`.

```
python manage.py import_legacy_requests --parquet <path> --submitted-before <ISO date>
```

- `--parquet` (required) — the file produced by
  `request_migration/requests_to_parquet.py`. Read with `pyarrow`, already a
  backend dependency, so this adds none.
- `--submitted-before` (required) — the fixed cutoff. Required rather than
  defaulted so that no run depends on when it happened.
- `--dry-run` — report counts, write nothing.
- `--batch-size` (default 2000).

Every `CharField` value is truncated to its field length on the way in, and a
truncation is counted and reported. The observed maxima above all fit, but
`custom_name` at 96 against a limit of 100 has little room and the old system is
still accepting submissions, so an over-long value must not be able to fail a
cutover run. `custom_name` keeps `Request`'s limit of 100 for parity rather than
being widened.

Rows are upserted with
`bulk_create(..., update_conflicts=True, unique_fields=["id"], update_fields=[...])`,
keyed on the preserved ObjectId. Re-running is therefore safe and the cutover
run is a plain repeat with a later date, which is the same "safe to re-run"
contract `adopt_legacy_users` already offers.

After writing, the command claims the new rows for any already-verified email
addresses, so a user who signed in before the import does not have to
re-verify to see them.

It reports created, updated, and skipped-with-reason counts.

### Ownership

Legacy requests are reachable the same three ways current ones are.

`accounts/claims.py` gains `LegacyRequest` alongside `Request` in
`claim_requests_for_email`, keeping the unclaimed-only (`user__isnull=True`)
semantics that make claims permanent and race-free under `ACCOUNT_UNIQUE_EMAIL`.

`analytics/services.py` gains `legacy_requests_for_user()`, mirroring
`requests_for_user()` exactly: FK-claimed rows unioned with live `iexact`
matches on verified addresses. Mirroring rather than generalizing keeps the two
readable side by side; if they drift, the bug is visible in a diff.

### API

Parallel endpoints, not a changed response shape. The current list responses are
bare JSON arrays consumed by the web UI *and* the MCP server, and
`requests_for_user` is shared between them specifically so the two can never
disagree about what someone owns. Adding a key to those payloads is a breaking
change across both consumers to serve a section rendered separately anyway.

New, in `analytics/`:

- `GET /api/analytics/legacy-requests/` — `IsAuthenticated`, via
  `legacy_requests_for_user()`.
- `GET /api/analytics/legacy-history/<token>/` — the magic-link flow, reusing
  `RequestToken` and its expiry handling unchanged.
- `GET /api/analytics/legacy-requests/<id>/` — detail. `AllowAny`, matching the
  existing `RequestDetailView`: a request id is already the capability.

List rows carry `id`, `name`, `submit_time`, `complete_time`, `dataset_count`.
Detail adds `boundary_title`, `dataset_titles`, and the download link. Every
payload sets `status_label: "completed"` and `is_legacy: true` — the flag the
UI keys its treatment off.

### Frontend

`api.ts` gains a `LegacyRequest` type and `fetchMyLegacyRequests`,
`fetchLegacyRequestsByToken`, `fetchLegacyRequestDetail`.

**List** — `routes/requests/[[token]]/+page.svelte` fetches current and legacy
in parallel. Current requests render exactly as today. Below them, a
`Collapsible` (the shadcn component is already vendored) labelled *"Archived
requests (2016–2026)"* with a count, **collapsed by default**: for most users
this is the longer list, and it is not what they came for. Rows inside use
muted styling and an `Archive` badge, and link to the legacy detail route.

A user with no legacy requests sees no section at all.

**Detail** — a new route `routes/requests/legacy/[id]/+page.svelte`. Its own
page rather than a branch inside the existing detail page: it shows name,
submitted and completed dates, boundary title, the dataset titles, and a
download button, and it has no task progress, no visualization, and no re-run.
Branching the current page on `is_legacy` would mean suppressing most of it.

The id is a 24-hex ObjectId, which the existing `[id=uuid]` param matcher
rejects. The separate `/requests/legacy/[id]` path leaves that matcher
untouched and makes the distinction visible in the URL.

### Stats

`stats/builder.py` adds `legacy_request_count` to the snapshot — a single
`COUNT(*)`, consistent with the snapshot's existing replica reads.

Reported separately on the stats page ("48,666 historical requests") rather
than folded into `status_counts` or the time series. Folding it in would put a
decade of another system's throughput into charts describing this one, while
dropping it would lose the full-decade figure the GeoQuery paper's impact
metrics want.

## Testing

Command:

- `--submitted-before` excludes rows at or after the cutoff.
- Non-completed rows are excluded.
- Rows with empty contact, empty boundary, or zero datasets are skipped, and
  each skip is counted by reason.
- Re-running the same import creates nothing and leaves row contents unchanged
  except `imported_at` — the idempotency guarantee the cutover depends on.
- A second run with a later cutoff adds only the newer rows.
- `--dry-run` writes nothing.

Ownership:

- Verifying an email claims matching legacy rows, and only unclaimed ones.
- `legacy_requests_for_user` returns FK-claimed rows and verified-email matches,
  and never another user's rows.
- An expired `RequestToken` is rejected by the legacy history endpoint.

Links:

- `LEGACY_DOWNLOAD_BASE_URL` set to an explicitly empty value produces no
  `download_url` key. Leaving it unset inherits `DOWNLOAD_BASE_URL` and does
  produce one, which is the default.
- Set to a URL, it produces `{base}/{id}.zip`.

Frontend: `bun run check` passes; a user with no legacy requests renders no
archived section.

## Documentation

`AGENTS.md` is not affected. The import command's docstring carries the
operational detail, as `adopt_legacy_users` does — including that it is
expected to run twice and is safe to re-run.

## Out of scope

- Mapping legacy datasets or boundaries onto current `Dataset` /
  `FeatureCollection` rows. The stored names are shown as text, by decision.
- Re-running, re-processing, or visualizing a legacy request.
- Exposing legacy requests through the MCP server, the public API, or STAC.
- Importing failed legacy requests.
- Backfilling `extract_data` or `RequestMap` rows for legacy requests.
- Hosting the zip archive. This spec consumes a base URL; producing it is a
  separate operational task.
