# Pair cursor leases: create background tasks when they finish

Status: design proposal, originally 2026-09-29; updated against repository code
on 2026-10-09. **Implemented on 2026-10-19** (not yet released), following
`new-extract-task-system-plan.md` rather than this document's rollout section:
leases replace the builder for every dataset at once, non-global datasets
included, and there is no per-dataset opt-in. The contracts as built are in
[database.md §12](docs/get-involved/contributing/dev/database.md). No
measurements have been taken yet; nothing below about expected gains has been
confirmed.

Deviations from the plan, as implemented:

- Infrastructure-failure backoff is counted per worker process, not stored on
  the lease: a failed page is returned unpenalized and the slot itself backs off
  exponentially (capped at five minutes).
- Two counters instead of one generation: `generation` drives sync, and `epoch`
  (invalidations only) is what work fences on. Additive changes no longer fail
  completions, re-token leases, or hold back task claims and request output.
- Invalidations are targeted where possible: a reshaped feature, a changed
  resource path or a changed option definition is logged in
  `extract_invalid_items`, and only those tasks are reset, hidden and
  rewound. Whole-scope resets remain for dataset path/type/mapped, category
  maps, extent and moves between datasets.
- A reset deletes background tasks (no request links them) with their results,
  and the publish rewinds their pairs; only request-linked tasks return to
  pending. The error sweep likewise deletes a retired pair's failures that no
  request needs.
- Materialization defers while an input scope it reads is being reset as a
  whole, has a targeted reset pending, is bootstrapping, missing, or held by a
  writer. Additions do not defer it.
- A collection whose state a writer holds blocks scans from passing its
  features. A collection being reset as a whole is skippable only above its
  `rewind_from`; logged features are skipped and come back with the publish.
  Inserts into one collection serialize on its state row, so a late commit can
  only interleave across collections. Upload collections record no changes for
  feature inserts and deletes, and caps ignore upload features.
- A collection publish takes no dataset states (the plan held all of them
  shared), and a lock timeout in sync is contention, retried without backoff.
- Claim discovery and the demand function share one SQL definition of runnable
  work (`extract_runnable_tasks`), and readers one of valid results
  (`extract_valid_tasks`), checked inside their own statements.
- Page size adapts per pair: a moving average of compute time per feature sizes
  pages to a quarter of the lease, and a timed-out page is cut to that size at
  takeover. Partial completion at the deadline is not implemented.
- `reset_extract_data` is removed; `invalidate_extract_inputs` replaces it.
- The internal coverage endpoint now serves status 1 only, like the public one,
  and Explore now requires status 1 (it previously served failed tasks' values).
- Hash collisions back a pair off for a fixed five minutes, with the error on
  the pair.
- `completed_up_to_fm_id` is renamed `cursor_fm_id`. Dataset ingest now diffs
  category maps instead of deleting and recreating them, since every write to
  a mapped dataset's maps resets its results.
- Added `extract_work_status`, `rewind_pair_cursors` (which did not exist
  before) and `invalidate_extract_inputs` commands. Query tags now cover every
  connection alias.
- Measured locally: the capture triggers took a one-INSERT-per-feature ingest
  from ~1.9 to ~2.5 ms per feature; `bulk_create` was unchanged within noise.
- A lease claim or coverage chunk locks its pair or watermark before it reads
  the window and its collections, and a collection publish locks every
  watermark and current pair before rewinding. With the plan's
  discover-then-guard order, a publish that committed between discovery and
  the scan, or ran while the scan was in flight, could leave a cursor past a
  feature with no pending rewind.
- A shape change deletes that geometry's coverage in its trigger instead of
  sync deleting the referencing collections' coverage chunk by chunk, which
  removed coverage below the rewind. FeatMap geometry and owner changes no
  longer reset coverage at all; their rewind re-examines the feature.
- The `extract_tasks.po_id` foreign key is dropped with its index; deleting an
  option deletes its tasks in a partition-pruned statement.
- Request output captures task status, and rereads the tasks' collections,
  after the input epochs, so a reset published after the readiness check is
  not merged.
- Deferred: an append-only rewind log (publish is O(pairs) today), partial page
  completion, partition-level whole-dataset resets, and a partition-pruned
  delete path for FeatMap deletions (re-ingest with `--reload-geometry` still
  goes through the ORM cascade).

Related: the [database decisions record](docs/get-involved/contributing/dev/database.md),
the [extract worker](backend/analytics/extract_worker.py),
the [claim and result writer](backend/analytics/tasks/processing.py), and
the [pair builder](backend/analytics/management/commands/build_extract_tasks.py),
[worker settings](backend/geoquery/settings.py), and
[worker metrics](backend/analytics/metrics.py).
Some lifecycle and tuning notes in the database record describe earlier
implementations; the current-code baseline below follows the worker and settings.

## Summary

Background extraction work is currently created far in advance. The builder
inserts one `extract_tasks` row per future extraction. A standalone worker now
claims a chunk directly from pending to running, computes tasks one at a time,
then persists their results and terminal statuses together. This has removed
the queued transition and per-task completion transactions. Each successful
task still requires an advance INSERT and two status UPDATEs, and claims still
use a fleet-wide advisory lock.

This proposal stops creating background task rows in advance. A worker leases a
page of up to ~256 features from a **pair cursor** that already exists
(`extract_task_build_progress`). It computes the page, then inserts the finished
task rows and their results in **one transaction**, building on the existing
chunk worker and bulk writer. Successful background task rows are then written
once; failures enter the existing bounded retry path.

Requests, retries and any already-materialised backlog keep using the current
task-row chunk path. The 255M pending rows cited below are a September snapshot,
not a current backlog count.

Expected incremental benefits, to be checked against the current chunk path:

- Remove the two remaining task-status updates and advance pending-row storage.
- Batch input reads by pair and geometry page, and move them to a standby.
- Reuse each open dataset resource across the lease's features where the
  processor supports it, amortising filesystem setup over the page.
- Avoid the global claim lock and pending-index cleanup costs on the lease path.
- Retain buffered computation and bulk result writes already used by chunks.

The original 2–4× WAL, 50× connection-time and 2.5–4k tasks/s projections used
the older Celery path as their baseline. They are not estimates of the remaining
gain over today's code; fresh measurements are required.

## Background for readers new to PostgreSQL internals

A few mechanisms explain almost all of the measurements below.

- **Updates create a new row.** PostgreSQL never changes a row in place. An
  `UPDATE` writes a complete new copy of the row and marks the old one dead.
  Every index on the table gets a new entry pointing at the new copy, unless
  the update qualifies as a *HOT update*. HOT is impossible here, because
  `status` appears in the pending index's `WHERE status = 0` condition. Dead
  rows and dead index entries stay until **VACUUM** removes them.
- **Write-ahead log (WAL).** Before any change reaches the table files, it is
  written to the WAL. A synchronous commit waits for WAL to be flushed to disk
  (`fsync`); the current processing path defaults to asynchronous commits,
  which acknowledge before that flush. This changes commit latency, not the
  amount of WAL generated. The September measurements below used an older path.
- **Checkpoints and full-page images.** Every few minutes a *checkpoint* writes
  all changed pages to the table files. The first change to any 8 KB page after
  a checkpoint logs the **entire page** into the WAL, not just the change, so
  that a crash mid-write can be repaired. Touching many "cold" pages is
  therefore far more expensive than repeatedly touching a few "hot" ones.
  Full-page images dominated WAL in the historical measurements below.
- **Connection pool.** Workers reach the database through pgBouncer. The
  September measurement used 50 server connections for 256 worker processes;
  these are historical sizes, not deployment requirements. A worker holds a
  server connection for the length of each transaction,
  including the time spent waiting for its commit to flush. If the flush is
  slow, the pool fills and other workers queue.
- **Partitions.** `extract_tasks` and `extract_data` are split into one
  partition per dataset (`extract_tasks_ds_23` is dataset 23). Every query must
  filter on `dataset_id` (database.md §1).

Vocabulary used below:

- A **pair** is one set of dataset resources (one raster, or 12 monthly rasters
  for a grouped dataset) combined with one processing option (such as `mean`).
- A **task** is one pair applied to one feature (a boundary).
- A **worker chunk** today is a batch of already-created task rows owned by one
  worker slot. It can span pairs and datasets. A proposed **lease page** instead
  owns feature IDs for one pair, keeping work grouped by resource or resource
  group. Optional **geometry fetch batches** control database reads and input
  memory within that page; they do not define the resource-processing unit.
- Each pair has a row in `extract_task_build_progress`, whose
  `completed_up_to_fm_id` column records how far through the features the
  builder has got. That row is the **pair cursor**.

## Current implementation and historical motivation

The implementation below reflects repository code on 2026-10-09. The production
tables that follow describe 2026-09-26 through 2026-09-29 on `geoquery-db-9`;
they establish the original motivation, not current throughput or WAL costs.

### Today's task lifecycle

```
builder    INSERT extract_tasks (status 0 = pending)     ← work waits in Postgres
claim      UPDATE a chunk 0 → 2 (running)    under a fleet-wide advisory lock
worker     load each task's inputs; compute; buffer outcome tuples in memory
flush      UPDATE accepted tasks 2 → 1 / −1, DELETE replaced results,
           COPY new extract_data rows                   (one transaction)
```

`run_extract_worker` runs independent process slots. Each slot claims only when
it is ready, using `EXTRACT_TASK_CLAIM_BATCH` (repository default 64; deployments
can override it). There is no Celery extraction message, prefetch, successor
dispatch or beat top-up. An empty or failed claim backs off with jitter around
`EXTRACT_WORKER_IDLE_SECONDS` (default 60 seconds).

Claim and flush are already amortised across the chunk. Input reads still
happen per task on the primary: `_load_claimed_task` reads geometry with
`ST_AsBinary`, followed by resource and, for mapped datasets, category lookups.
Processing recomputes all resource positions; it does not read or merge previous
results. Computation holds no transaction or row lock.

`_persist_outcomes` checks `status = 2` and the loaded `update_time` claim stamp
in its terminal UPDATE, then replaces results only for accepted tasks. It uses
aligned arrays with explicit dataset filters and streams result tuples through
COPY. `_flush_outcomes` retries transient database failures from memory (up to
three attempts) and recursively splits batches on data/encoding errors to
isolate a bad task. These persistence features are already present.

On graceful stop, each slot finishes its current task, flushes computed outcomes
and returns unstarted tasks to pending. Unresolved claims after a failed flush
are also released. Abrupt process death leaves rows for the stale-task reaper;
the parent replaces only the failed slot. Chunk duration therefore matters for
both request latency and the reaper's age limit (default 30 minutes).

The normal successful lifecycle now leaves **two**, not three, dead task-row
versions. Processing claim, release and flush default to asynchronous commit
(`EXTRACT_TASK_SYNCHRONOUS_COMMIT=0`). Any lease durability comparison must
account for that setting as well as chunk size and workload.

### Where the WAL went in September

These figures are from `pg_stat_statements` over the 81 hours since the stats
reset on 2026-09-26 12:30 UTC.

| Statement | Share of WAL | WAL per task | Full-page images per task |
|---|---|---|---|
| Claim `UPDATE` 0 → 3 | **60%** | 4.5 KB | 1.1 |
| Builder `INSERT` | 13% | 1.9 KB | 0.4 |
| Worker `UPDATE` 3 → 2 | 10% | 0.74 KB | 0.08 |
| Worker `UPDATE` 2 → 1 | 7% | 0.5 KB | 0.02 |
| `extract_data` `INSERT` (the actual results) | 3% | 0.26 KB | 0 |

The original analysis estimated about 7.9 KB of WAL per task over its lifetime,
with result INSERTs accounting for only 3% of sampled WAL. This is not a fresh
per-task measurement of the current chunk implementation.

The old claim was the expensive step because it made the first write to rows
created long ago:

- The pending row's pages have gone cold, so the claim's write pays for a
  full-page image.
- Its index entries sit in indexes ordered by `fm_id` first, while work
  proceeds one pair at a time. Consecutive claims therefore touch pages that
  nothing has written recently.
- The 3 → 2 and 2 → 1 updates were cheap because the claim warmed those
  pages moments earlier.

### Historical evidence of a write limit

| Test (2026-09-29) | Result |
|---|---|
| Unthrottled `VACUUM` of `extract_tasks_ds_23` | Claim time fell from 136 ms to 1.5 ms, but throughput only moved from 968 to 1,045 tasks/s. The claim was no longer the limit. |
| Pool size 20 → 25 per pooler | Throughput went from 999 to 1,050 tasks/s (not significant). The extra connections spent their time waiting on the WAL. |

During the pool-25 test:

- Connection time split into 31% waiting on WAL writes, 32% executing and 30%
  in round trips to workers.
- The primary's data volume was 93–95% busy, with 7.6 ms write latency.

In those tests, faster claims and more connections did little for throughput.
Chunk completion, COPY, asynchronous commits and subsequent database tuning
have since changed the baseline. Measure the current limiting resource before
assigning a throughput target to leases.

### The historical pending backlog also had a cost

- Pending rows (status 0) numbered about 255M (ds_23 184M, ds_24 72M): about
  three days of work at the measured September speed.
- The pending index alone was 25 GB.
- Dead entries pile up at the head of that index until VACUUM runs. Each claim
  has to walk past them, which is the "claim slows down between vacuums"
  sawtooth.
- The claim serialises the whole fleet on one advisory lock (database.md §2).

## The design

### Idea

Stop materialising background work ahead of time. The pair cursor already
records how far each pair has got. Hand out **pages of the cursor** to workers
instead of pre-built rows, and create task rows only when the work is finished:

```
claim      lock one pair row, pick the next ≤256 features, INSERT one lease row,
           advance the cursor                                    (1 transaction)
load       read pair metadata and the page's geometries from a standby
                                                     (autocommit, no primary)
compute    open each resource and reuse it across the page's features
           where supported                                     (no database)
complete   check lease, INSERT all task rows as status 1 / −1,
           COPY all accepted results, DELETE lease               (1 transaction)
```

For a successful leased task, the only task/result writes are its terminal task
row and its results. The lease table adds claim, takeover and deletion writes
per page. The current chunk worker already buffers outcomes; the new part is
delaying task creation and replacing row claims with pair-page ownership.
Keep the lease grouped by resource or resource group, and make resource reuse
explicit in the processor interface. Geometry fetch size is a separate tuning
choice, not a reason to repeatedly reopen the same resource.

### New table: `extract_task_leases`

This is a small working table holding one row per page currently being
processed. It grows with active workers (hundreds of rows), not with history.

| Column | Meaning |
|---|---|
| `id` | bigserial primary key |
| `progress_id` | the pair (`extract_task_build_progress.id`) |
| `dataset_id`, `resource_ids`, `po_id`, `task_group_period` | copied from the pair, so recovery and completion don't need to re-derive them |
| `fm_ids integer[]` | the exact features in this page, fixed at claim time |
| `token uuid` | changes every time the lease is (re)assigned |
| `leased_until timestamptz` | after this, anyone may take the lease over |
| `attempts integer` | how many times it has been assigned |
| `created_at timestamptz` | for monitoring the oldest outstanding work |

It needs one index, on `leased_until`, to find expired leases.

### 1. Claim

Two cases.

**First, take over an expired lease, if there is one.** Leases are reclaimed
before any new pages are handed out, so abandoned work is never skipped:

```sql
UPDATE extract_task_leases
SET token = gen_random_uuid(), leased_until = now() + :lease_duration,
    attempts = attempts + 1
WHERE id = (SELECT id FROM extract_task_leases
            WHERE leased_until < now()
            ORDER BY leased_until
            FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING *;
```

**Otherwise, take a new page from a pair cursor.** This runs in one
transaction. Use the observed maximum feature ID as `:max_fm_id`. After locking
the pair, set `:scan_end = min(:cursor + :scan_window, :max_fm_id)` and use that
same boundary for both the feature scan and cursor advancement:

```sql
-- a) lock one pair that has work left; SKIP LOCKED means concurrent workers
--    take different pairs instead of waiting for each other
SELECT p.id, p.resource_ids, p.po_id, COALESCE(p.completed_up_to_fm_id, 0),
       dr.dataset_id, d.task_group_period
FROM extract_task_build_progress p
JOIN dataset_resources dr  ON dr.id = p.resource_ids[1]
JOIN processing_options po ON po.id = p.po_id AND po.active
JOIN datasets d            ON d.id = dr.dataset_id AND d.active AND d.is_global
WHERE dr.dataset_id = ANY(:lease_datasets)
  AND COALESCE(p.completed_up_to_fm_id, 0) < :max_fm_id
ORDER BY p.id
FOR UPDATE OF p SKIP LOCKED
LIMIT 1;

-- b) the next eligible features after the cursor that have no task yet
--    (a request may already have created some), recorded as one lease row
INSERT INTO extract_task_leases
    (progress_id, dataset_id, resource_ids, po_id, task_group_period,
     fm_ids, token, leased_until, attempts, created_at)
SELECT :pair_id, :dataset_id, :resource_ids, :po_id, :period,
       array_agg(fm.id ORDER BY fm.id), gen_random_uuid(),
       now() + :lease_duration, 1, now()
FROM (
    SELECT fm.id FROM feat_map fm
    JOIN feature_collections fc ON fc.id = fm.fc_id
    WHERE fc.active AND NOT fc.is_user_upload
      AND fm.id > :cursor AND fm.id <= :scan_end
      AND NOT EXISTS (
          SELECT 1 FROM extract_tasks et
          WHERE et.dataset_id = :dataset_id AND et.fm_id = fm.id
            AND et.po_id = :po_id
            AND et.resource_ids_hash = extract_tasks_resource_ids_hash(:resource_ids)
            AND et.resource_ids = :resource_ids AND et.kwargs IS NULL)
    ORDER BY fm.id
    LIMIT :page_size
) fm
HAVING count(*) > 0
RETURNING id, token, fm_ids;

-- c) advance the cursor past what was examined: the last leased feature,
--    or :scan_end if the page came back short (including an empty page)
--    :new_cursor = last leased fm_id for a full page, otherwise :scan_end
UPDATE extract_task_build_progress
SET completed_up_to_fm_id = :new_cursor
WHERE id = :pair_id;
```

Four points about this transaction:

- **No fleet-wide lock on lease claims.** Workers contend only when they want
  the same pair, and `SKIP LOCKED` sends them to different pairs. The September
  inventory found about 2,100 unfinished pairs; recheck available parallelism
  for the pilot. Task-row claims retain their existing advisory lock.
- **The cursor means "leased", not "done".** It moves only in the same
  transaction that creates the lease covering those features. If the
  transaction rolls back, both are undone together.
- **`:scan_window` bounds the work.** A stretch where requests already created
  every task can't turn one claim into a long scan; the cursor just advances
  past an empty window. Capping `:scan_end` at `:max_fm_id` prevents advancing
  beyond the observed feature IDs and skipping features ingested later.
- **The cursor's coverage contract expands:** currently it tracks the builder's
  examined feature range; with leases, eligible work in that range must have a
  task row or a durable lease. Cursor exhaustion does not mean processing is
  complete. The builder and new lease claims must never advance the same
  dataset's cursors concurrently (see Rollout).

### 2. Load

Routine loading reads from a standby through the read-only pooler
(`.using("replica")`, or `connections["replica"]` for explicit WKB queries).
It runs in autocommit, with no transaction spanning queries and computation,
and no lock held on the lease row. Apart from freshness checks and fallback
reads described below, the primary sees only claim and completion.

- **Pair metadata, once per lease:** resource records, the processing option
  and the category mapping. Loading these database rows does not open the
  underlying files. Resource files come from `/data`; opening and reusing them
  is part of Compute below.
- **Geometries for the lease page:** start by fetching the whole page in one
  query and reuse those geometries across its resources. Introduce smaller
  fetch batches only if measured memory use or database connection occupancy
  justifies them. There is no fixed 32-feature batch requirement.

There are no existing results to read. Today's chunk worker also recomputes
all positions without reading prior results, so this is not an additional
saving from leases. The read savings come from sharing pair metadata and
batching geometry reads instead of loading each task independently.

**Geometry fetch sizing.** Measured on a standby on 2026-09-30, over the 955,650 active,
non-upload features:

| | Median | p90 | p99 | Max |
|---|---|---|---|---|
| One feature | 608 B | | 68 kB | 84 MB (an ADM1) |
| A 256-feature page in `fm_id` order | 170 kB | 3.9 MB | 16 MB | 89 MB |

Geometries barely compress, so the stored size is about the WKB size. The old
ORM geometry load used a raw geometry column with a hex representation. Today's
worker explicitly selects `ST_AsBinary(g.shape)` and passes WKB to Shapely;
the lease loader should retain that approach. Measure actual wire bytes under
the deployed driver/protocol rather than carrying forward a fixed 2× factor.

These figures support starting with a whole-page fetch: the median page is
small, and the largest page is dominated by one huge feature. A smaller batch
cannot remove that single-feature memory cost. They do not establish an optimal
fetch size, especially after geometry decoding and processor allocations.

Measure peak worker memory and database read duration with the actual lease
sizes and concurrency. Include open-resource buffers and the results retained
until completion. Smaller fetch batches can reduce geometry memory and time
per database read, but add round trips. If needed, choose their size and the
resource lifetime together so database batching does not defeat filesystem
reuse. Resource grouping remains the processing strategy in either case.

**Why a standby.** Every task still loads one geometry, as it does today.
That's 5.6 kB of WKB per task on average:

- about 6 MB/s of WKB at the September rate of ~1,050 tasks/s;
- about 20 MB/s of WKB at an illustrative 3.5k tasks/s.

These were comparable to the historical WAL rate (12–14 MB/s). Keeping geometry
reads on the primary consumes three resources:

- Network bandwidth; the September primary's 1 GbE NIC was at ~90% transmit.
- Primary pool connection time. Today's geometry read is a separate SELECT,
  with no locking 3 → 2 transaction, but still occupies a server connection
  while it executes and transfers the result.
- Cache space shared with task indexes; the measured feature set held about
  5.4 GB of geometry. Recheck the working set and cache pressure in the pilot.

**Replication lag.** The lease's `fm_ids` and `resource_ids` are chosen on the
primary. A feature or resource ingested moments earlier may not have reached
the standby yet. If a geometry or resource query comes back short, read the
missing IDs from the primary before treating them as unavailable.

Missing-row fallback alone does not guarantee freshness: dataset resources can
be updated in place by ingestion, and dataset/option/collection activity can
change. Define a consistency rule before enabling replica loads (for example,
a replay-position barrier after claim, with primary fallback on timeout).
Retain the current loader's active dataset, processing-option and collection
checks, and define how ineligible work is resolved without silently losing
cursor coverage. Do not assume all input metadata is immutable.

### 3. Compute

Process the lease by resource or resource group, with no open database
transaction. Where the processor supports it, open a resource once, apply it
to the page's assigned features, then close it. For a grouped pair, a resource
at a time can reuse the loaded geometries without requiring every resource
file to stay open simultaneously. Reusing an open resource does not require
loading the entire file into memory; retain windowed or filtered reads where
supported.

For example, for one raster and 256 features, fetch the page's geometries, open
the raster, process the features against that open raster, and close it. If
geometry fetching is later split into smaller batches, preserve resource reuse
across those batches where supported and within memory/file-handle limits.

This needs an explicit processor capability, such as a resource context or a
batch interface. Today's raster wrapper takes one geometry and a file path per
call; merely grouping those calls into a lease does not establish open-file
reuse. Adapt processors that support reuse and retain the current call path as
a fallback for others. Preserve extraction semantics and isolate failures per
feature and resource even when inputs are shared. Close resource handles on
success, failure and graceful abandonment; keep them local to the worker process.

Buffer results by feature and resource position until lease completion, retaining
the existing position alignment with `resource_ids`. Each feature produces
results or a failure; grouped-task resource failures still leave NULL positions
plus an error. Computation and filesystem I/O hold no database connection through
an open transaction.

### 4. Complete

Result rows follow the current writer's storage contract, with one row per
`(dataset_id, extract_task_id, name)` and no `data_column` discriminator:

- For one resource, populate the appropriate scalar column (`int_value`,
  `float_value` or `str_value`) and leave the array columns NULL.
- For multiple resources, populate the appropriate array column (`int_values`,
  `float_values` or `str_values`), position-aligned with `resource_ids`, and
  leave the scalar columns NULL. Choose the type from the first non-NULL result
  in resource order, so a leading nodata result cannot determine the row's type.
- For a named result that is nodata at every position, insert the result row
  with all six value columns NULL. Successful nodata still completes the task
  as status 1; NULL values do not imply unfinished work. A resource failure
  also leaves its position NULL, but makes the task status −1 with an error.

The normal bulk completion is one transaction, committed synchronously. This is
a deliberate proposal choice, unlike the current chunk writer's default async
commit. Keep claim plus cursor advancement atomic too; start the pilot with
synchronous lease claims and completions, and measure that durability choice
explicitly rather than inheriting `_execute_async` accidentally.

```sql
-- a) still ours? If the token changed, the lease was taken over: roll back and
--    discard the results. Whoever holds the current token will write them.
SELECT 1 FROM extract_task_leases WHERE id = :lease_id AND token = :token FOR UPDATE;

-- b) all task rows at once, already finished
INSERT INTO extract_tasks
    (dataset_id, resource_ids, task_group_period, fm_id, po_id, status, priority,
     attempts, submit_time, start_time, update_time, complete_time, error)
SELECT :dataset_id, :resource_ids, :period, r.fm_id, :po_id, r.status, 0,
       0, :claimed_at, :claimed_at, now(),
       CASE WHEN r.status = 1 THEN now() END, r.error
FROM unnest(:fm_ids, :statuses, :errors) AS r(fm_id, status, error)
ON CONFLICT (dataset_id, fm_id, po_id, resource_ids_hash) WHERE kwargs IS NULL
DO NOTHING
RETURNING id, fm_id;

-- c) stream result tuples using the current COPY approach, remapping fm_id
--    to the task IDs returned above; omit results for conflicting tasks
COPY extract_data (dataset_id, extract_task_id, name,
                   float_value, int_value, str_value,
                   float_values, int_values, str_values) FROM STDIN;

-- d) the lease is done
DELETE FROM extract_task_leases WHERE id = :lease_id;
```

Row lock (a) is what makes takeover safe. Takeover changes the token while
holding the same row lock, so exactly one of "old worker completes" and "new
worker takes over" happens first, and the other sees it.

**Reuse buffering and encoding, adapt recovery.** The existing writer already
builds COPY-ready tuples, fences task-row completion, retries transient errors
and splits bad batches. A lease writer can share result encoding and bounded
in-memory retries, but cannot call `_persist_outcomes` unchanged: there are no
task IDs until insertion, fencing uses the lease token, and independent commits
of split batches would break the page's atomic completion/deletion contract.
Every retry must reacquire the lease lock and check ownership. If a commit
response is lost and the lease is already gone, discard the buffer; never
recreate or rewind that lease based only on the lost response.

**Fallback for result-data errors.** A processor can return successfully but
produce a value that cannot be stored. One such feature must not force the
whole page to repeat forever. Try the bulk completion once. If it fails with
a recognized result-data error, let the entire transaction roll back, then
retry storage immediately using the results already in memory:

1. Open a new transaction, lock the lease and check its token again. If the
   lease is missing or its token has changed, discard the results. Ownership
   may have changed between the two transactions.
2. For each feature, insert its task and results inside a separate savepoint.
   If a recognized result-data error occurs, roll back that savepoint, then
   insert the task as status −1 with an error bounded to the column's length
   and no result rows. Continue with the other features.
3. Delete the lease and commit synchronously. The valid results, failed task
   records and lease deletion still commit together.

The recognized errors are a narrow allowlist, matched by SQLSTATE and the
operation that failed: string-too-long (`22001`), numeric overflow (`22003`)
and invalid text representation (`22P02`) while encoding or inserting result
values. Do not classify errors by message text or treat every database error
as a bad feature. Connection failures, deadlocks, schema errors, unexpected
constraint violations and errors writing task metadata abort completion and
leave the lease recoverable. If writing a failed-task record itself fails,
abort the fallback transaction too.

In Django, each per-feature savepoint is a nested `transaction.atomic()`
block. Catch its error outside that inner block, after the savepoint has
rolled back, so the outer transaction remains usable. Rebuild task/result
objects and their ID mappings after rollback; IDs returned by the aborted
bulk attempt do not identify persisted tasks.

Both the per-feature insertion and the failed-task insertion retain
`ON CONFLICT DO NOTHING`. If a request already created the task, leave it
alone and write no lease results for it. All result rows for one feature
share its savepoint, so a storage failure leaves none of that feature's
results behind. Ordinary processing failures can still retain their valid
partial results as described above.

Successful pages pay no additional database operations. Only a failing page
pays for the aborted bulk attempt and up to one savepoint per feature; there
are no geometry reloads or repeated extraction calls during fallback. Measure
the fraction of pages entering fallback and their completion duration. Start
with this simple loop; consider splitting failed batches into smaller batches
only if measurements show the fallback cost matters.

Status −1 preserves today's retry policy: the ten-minute
`manage_processing_task_errors` returns the task to pending and increments
`attempts` while below `MAX_EXTRACT_TASK_ATTEMPTS` (default 5). The current chunk
worker retries it; exhausted tasks remain failed. This isolates a bad feature
from its neighbors without introducing a new retry policy. Lease assignment
`attempts` are separate from task retry `attempts`.

### Worker loop and ordering

Extend the existing `ExtractWorker` slot loop. Each free slot chooses and claims
one unit of work immediately before running it; there is no extraction message
or broker queue to add. The current claim helper selects globally by priority;
implementation will need a request-only claim mode before choosing between the
two background sources.

1. **Request work first.** Claim pending rows with `priority ≥ 1` and use the
   current task-row chunk path. Already-running chunks or leases are not
   preempted, so their duration bounds how quickly a busy slot can serve a
   newly arrived request.
2. **Then background work.** Allocate an explicit share between existing
   pending rows (including retries) and lease pages. Within the lease branch,
   recover expired leases before issuing new pages. Fall back to the other
   source when one is empty. Measure the share in worker time as well as chunk
   counts because page costs differ by dataset.
3. **When neither source has work,** retain jittered idle polling and connection
   cleanup. Pair discovery must continue independently so new resources can
   become visible even when no extraction worker is active.

Keep per-slot process isolation and recycling. Add a lease-aware shutdown path:
unlike today's task chunk, a partly computed lease cannot simply flush a prefix
and delete the whole ownership record. For the initial design, stop new claims
and finish the page within the termination grace period. If that is impossible,
discard buffered work and expire the lease under its token so another worker
can retry the exact page; a hard kill relies on normal expiry. Partial page
completion would require atomically retaining the remaining `fm_ids` in a lease
and is a separate extension.

### What happens when things go wrong

| Event | Outcome |
|---|---|
| Claim transaction fails | Lease and cursor advance roll back together; nothing is lost |
| Worker dies mid-lease | The lease expires. The next claimer takes it over first, with the same features and a new token. |
| Old worker finishes after takeover | Its token check fails. It writes nothing. |
| Bulk completion fails with a recognized result-data error | Roll back, then retry storage from memory with per-feature savepoints and a fresh lease-token check. Valid features and status-−1 records for unstoreable features commit together with lease deletion. |
| Completion fails for another reason, or fallback cannot finish | Nothing from that transaction commits and the lease stays recoverable. It is retried after expiry. |
| One feature's processing fails | Its task row is inserted as status −1 with the error and any partial results. The ten-minute `manage_processing_task_errors` sweep resets it to pending while below the configured retry limit; the current chunk path retries it. |
| A request needs a feature inside an active lease | The request creates its own pending row (priority 1), which is processed first through today's path. The lease's completion hits `ON CONFLICT DO NOTHING` for that feature. The cost is duplicate compute, not a wrong result. |
| A request needs a feature the lease already completed | It finds a status-1 row and reuses it, as today. |
| A request needs a feature beyond the cursor | It creates a pending row, and the lease claim's `NOT EXISTS` skips that feature later. |
| A feature or resource hasn't replicated to the standby yet | The load reads the missing ids from the primary (see Load) |
| A standby query is cancelled by a recovery conflict | Retry the geometry fetch with bounded backoff; verify replica settings and measure cancellations in the pilot. |
| Worker receives a graceful stop | Stop new claims; finish and commit the page, or discard its buffer and explicitly expire the owned lease. Never delete a partly completed lease. |
| All processing workers are scaled to zero | An independent demand check must wake workers for pending work, unfinished pairs or expired leases; worker-local metrics alone cannot provide recovery. |

### Lease duration and size

A lease that outlives its duration gets taken over while the first worker is
still computing. That wastes work, and the first worker's results are thrown
away. The duration is therefore a **time limit, not a liveness check**
(database.md §4).

- Size each dataset's pages so their expected run time is well inside the lease
  duration. For example, 256 features for fast single-raster datasets, and 1–8
  for the slow 12-resource grouped datasets (15–40 s per task).
- Start with a 15-minute lease. Monitor takeovers and rejected completions.
- If legitimate pages can exceed that limit, reduce their size or add fenced
  heartbeats before enabling those workloads. Monitor the oldest active lease
  as well as completed-page durations; stuck pages never enter a completion
  histogram.

### Autoscaling

Choose the controller and exact policy during implementation. A leasing system
needs demand signals that include work without task rows; neither pending-task
counts nor worker utilisation alone describes all of it.

- **Detect available work cheaply.** Combine bounded or cached checks for
  pending request/backlog rows, expired leases, and eligible pair cursors with
  work left. Prefer existence checks or maintained estimates to full backlog
  counts. Keep dataset filters on task-table probes. Distinguish leases already
  being worked from pages available to new workers, so active leases do not
  each create demand for another slot.
- **Size capacity by time and useful parallelism.** Use observed per-dataset
  page durations and completion rates, oldest waiting request age, active slots
  and idle time. A one-feature grouped lease and a 256-feature single-resource
  lease are not equal units of demand. Start with bounded scaling steps and a
  concurrency ceiling established by measurement.
- **Stop scaling when shared resources saturate.** Watch claim latency, flush
  latency, primary WAL/disk load, standby lag and read-pool waits, worker memory,
  and raster I/O. More slots are useful only while throughput or request latency
  improves without exhausting those resources.
- **Make recovery survive scale-to-zero.** Keep a small worker floor or an
  independent scheduled demand exporter/check that sees unfinished pairs and
  outstanding leases, wakes workers when leases expire, and keeps pair discovery
  running. A cursor at its end does not mean its leases have completed.
- **Drain on scale-down.** Stop new claims and allow time for completion, or
  explicitly expire an abandoned lease as described above. Use cooldowns that
  account for page duration and recovery delay; do not interpret quiet completion
  counters during a long page as an idle fleet.

The existing `geoquery_extract_*` metrics provide slot counts, active chunks,
oldest chunk age, claim timing, phase timing, completion counts and flush
retries. Extend them with lease availability, age, takeovers and rejected
completions, and ensure lease execution participates in slot-state metrics.
Keep demand collection available independently of the worker pods it controls.

### Things that stay the same

- Request submission, materialisation, `RequestMap` and completion checks.
- Today's claim, worker and retry path, used for requests, retries and the
  legacy backlog.
- `extract_data` storage: scalar values for single-resource tasks,
  position-aligned arrays for grouped tasks, and all-NULL named nodata rows.
- Task identities: a background task gets its ID when it is inserted at
  completion, and keeps it forever.

## Rollout

1. **Opt in per global dataset** with a setting such as
   `EXTRACT_TASK_LEASE_DATASETS`.
   - This proposal uses the global builder's pair cursors. Non-global coverage
     work continues through its existing builder and task-row path.
   - The builder skips pairs of those datasets. Stop new builder claims and
     let in-flight builder work release its `claimed_at` ownership before
     enabling lease claims; changing a setting alone does not stop a builder
     that already holds a pair.
   - Pair discovery (`_SYNC_*_PAIRS_SQL`) keeps running.
   - A dataset's existing pending rows drain through today's path while leases
     continue from its cursor. Nothing needs converting.
   - Configure `PG_RO_*` for processing workers and verify actual routing.
     `_pg()` in `settings.py` falls back to `PG_RW_*` when read-only settings
     are absent, including in local Compose. A successful `.using("replica")`
     query does not by itself prove the load reached a standby.
   - Budget read-pool connections and bandwidth alongside API and tile reads.
     Check current pool sizes and placement; do not use the September node
     layout as a deployment assumption.
2. **Pilot on one small dataset with unbuilt pairs.** Refresh the inventory;
   the September estimate of 2,100 pairs across roughly 50 datasets is historical.
3. **Measure** (next section) for at least a day against the current chunk path
   in the same window, controlling for dataset mix and builder activity.
4. **Expand dataset by dataset.** Existing pending rows drain through the chunk
   path while leases cover new work beyond the cursor. Estimate drain time from
   the actual backlog and observed throughput at rollout.
5. **Roll back per dataset:**
   - disable new lease pages for it, keeping recovery and completion enabled;
   - drain all outstanding leases, including reclaiming expired ones: expiry
     alone does not create task rows behind the advanced cursor;
   - resume the builder only once that dataset has no outstanding leases.

If leases cannot drain, rollback needs an explicit transactional conversion of
remaining `fm_ids` to pending task rows, fenced against concurrent completion,
before deleting their leases. Never simply abandon leases and resume from the
advanced cursor.

## Pilot measurements and success criteria

First establish a baseline for today's chunk implementation with the pilot's
dataset mix, chunk sizes, commit settings and builder load. Use the September
figures only as historical context. Measure task-row and lease work separately
while both paths run.

| Measure | Source | Target |
|---|---|---|
| WAL and full-page images per task, leases vs current chunks | `pg_stat_statements`, total WAL over the window, completed-task counts | Lower total write cost including builder and lease overhead; quantify the gain against the new baseline |
| Connection time and statements per task | pgBouncer `SHOW STATS`, statement counts, worker phase metrics | Fewer primary input queries and lower connection occupancy; claim/flush batching is already in the baseline |
| Loads reach the standby | Statements on standbys, read-pool statistics, primary network traffic | Routine geometry reads off the primary; fallback reads rare and observable |
| Resource reuse | File-open counts, resource setup time and filesystem I/O per lease, by processor | Supported processors reuse each resource across assigned features; geometry fetch boundaries do not introduce repeated opens |
| Geometry fetch sizing | Peak worker memory, read duration and pool occupancy at pilot concurrency | Whole-page reads fit the resource budget; use smaller batches only when measurements justify their extra round trips |
| Lease health | Counts of takeovers, rejected completions, oldest lease age | Near zero, and bounded |
| Storage fallback | Fraction of pages entering fallback; fallback duration; features recorded as storage failures | Rare enough to preserve the bulk path's throughput benefit; bad features do not block their neighbors |
| Correctness | Results compared against the current chunk path for the same features; request reuse; bounded failure retries | Identical |
| Fleet throughput and resources | Worker completion/phase metrics, disk load and latency, memory, raster I/O | Throughput up at comparable resource use, without degrading request latency |
| Scheduling and recovery | Request wait time, shutdown, expired-lease recovery and scale-from-zero exercises | Requests remain responsive; outstanding work recovers even with all cursors at their end |

Verify fallback with one unstoreable feature among valid features, a request
inserting a conflicting task, takeover between the bulk rollback and fallback,
and a database failure during fallback. These must respectively preserve valid
neighbors, preserve the request's task, reject the old token, and roll back
fallback writes while leaving the lease recoverable.

Also exercise graceful stop mid-page, process death, commit-response loss,
replica lag or metadata changes, and dataset rollback with expired leases. Verify
that the advanced cursor never leaves work with neither a task row nor a
recoverable lease.

Compare resource-reusing processors with the current call path for the same
inputs, including grouped resources, nodata and one failing feature among valid
neighbors. Verify result alignment and handle cleanup. If smaller geometry
fetches are introduced, check both their memory benefit and their effect on
resource opens and filesystem I/O.

## Expected effect relative to current chunks

For the normal successful path (excluding retries, conflicts and fallback):

| | Current task-row chunks | Proposed leases |
|---|---|---|
| Task-row writes | Advance INSERT + claim UPDATE + terminal UPDATE | Terminal INSERT only |
| Claim/completion transactions | 2 per worker chunk, plus separate builder writes and per-task input reads | 2 per nonempty lease page, plus any empty-window scans |
| Result writes | Batched DELETE + COPY, fenced by task claim stamp | COPY for newly inserted tasks, fenced by lease token |
| Database input reads | Primary, per task/resource | Standby, metadata and geometries per lease page; smaller geometry fetches only if justified |
| Resource access | Processor receives a geometry and resource path per call | Reuse open resources across assigned features where supported; retain existing calls as fallback |
| Commit policy | Asynchronous by default, configurable | Synchronous for the initial pilot |
| Dead task-row versions per successful first run | 2 | 0 (lease rows still churn) |
| Fleet-wide task claim lock | Yes | Absent on lease branch; retained for task-row chunks |
| WAL, connection time, throughput | Establish a fresh baseline | Measure incremental improvement |

The remaining opportunity is fewer row versions, no speculative pending index
entries, shared/offloaded input reads, and amortised resource setup where
processors support reuse. Bulk completion and removal of the
queued transition must not be counted again as lease benefits. Inserting a
terminal task still touches the unique and feature indexes; the September
full-page-image costs motivate measuring that write pattern, not assuming a
particular saving. CPU, raster I/O, replica capacity and storage bandwidth may
become limits before the original throughput projection is reached.

## What this does not solve

- **The existing backlog.** Already-created rows keep their task-row lifecycle
  and drain through the current chunk worker.
- **Requests.** Their path is unchanged.
- **Results.** `extract_data` volume grows with completed work either way.
- **The cold-index cost of inserting task rows.** Reordering the unique index to
  `(dataset_id, po_id, resource_ids_hash, fm_id)`, and reviewing whether the
  separate `fm_id` index is needed, could cut it further. That is a separate
  investigation.
- **Storage hardware.** At some point the next limit is the storage itself.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep current chunks and tune their size | Already batches claims and completion; does not remove advance task rows or the two remaining status updates |
| Vacuum pending partitions more often | Helps task-row claims; the September test improved throughput only about 8%. Recheck the current bottleneck. |
| Bigger connection pool | The September gain was about 5%; extra connections did not resolve the measured write limit |
| Create task rows at claim time as running | Removes one of today's two status updates and advance pending storage, but retains a terminal UPDATE and dead row; can still use current bulk completion |
| A separate small queue table over pre-built tasks | Retains speculative task storage and a completion write to cold task pages |
| Bound builder output | Existing batch-size, per-worker task-cap and cadence settings help control materialisation load, but do not remove task status updates; a backlog-aware gate would be additional policy |

## Open questions

1. Page size and lease duration per dataset. Can they come from measured task
   durations rather than be configured by hand?
2. The share between leases and the legacy backlog while both exist.
3. Should failures create a task row (as proposed), or stay in the lease table
   for retry? Creating the row reuses existing retry and monitoring, at the
   cost of the existing retry lifecycle's updates.
4. Feature IDs are allocated before their transaction commits. A feature
   ingested concurrently can therefore commit with an ID *below* a cursor that
   has already moved past it. The builder has the same gap today. Decide whether
   feature ingestion should reset affected cursors.
5. Reactivated feature collections, or changed resource groups, need a rule for
   rescanning a pair from zero.
6. Logs and dashboards identify in-flight background work by lease ID and
   `fm_id`, since there is no task ID until completion. Check that nothing else
   expects running background tasks to have rows. Audit the stale-task reaper,
   monitoring and demand collection; extend the current slot/chunk metrics to
   cover leases rather than relying on status-2 task counts.
7. Each geometry is still loaded once per pair. In the September ds_23 inventory
   that was 366 times per feature (122 resources × 3 processing options).
   Unstarted pairs of a dataset all have their cursors at 0. One lease could
   cover a feature range across all of them: load each geometry once, and compute
   mean/min/max in one rasterstats pass. That would change the cursor model,
   so it is left for a follow-up.
8. What replica freshness and metadata-change policy should the loader enforce,
   including activity changes during a page? Missing-ID fallback alone is not
   sufficient.
9. Is full-page completion within shutdown grace practical for every dataset,
   or is atomic partial completion with a remaining-feature lease necessary?
10. Which processors can expose a reusable resource context or batch interface,
    and what memory and file-handle limits should govern it? Measure whole-page
    geometry reads first; select smaller fetch batches only where needed.
