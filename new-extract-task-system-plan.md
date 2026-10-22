# Implementation plan: pair cursor leases

Status: revised 2026-10-09 after review; implemented 2026-10-19 (uncommitted,
not released). Deviations are listed in `pair-cursor-leases-design.md`. This
supersedes the earlier grouped in-place reset and collection-count snapshot
proposal. One branch includes the bigint work from PRs #54/#55.

## 1. Shape and invariants

Replace speculative background `extract_tasks` with durable leases. A worker
claims a page for one `(resource_ids, processing option)` pair, computes outside
transactions, then inserts terminal tasks and results together. Requests and
ordinary retries retain the task-row path. Keep one cursor per pair, not a
pair-by-collection work table.

- **A cursor means accounted for, not finished.** Each eligible feature below
  it has a task or lease, or belongs to a dirty input scope with a durable rewind
  pending. Deleting a lease must leave one of those conditions true.
- **Task resource arrays are immutable.** A changed grouped bucket selects a
  new pair. Retire the old pair; never rewrite its arrays or relabel its results.
  Reusing an earlier identical set is allowed after rewinding.
- **Changes are transactional.** Small dataset/collection state rows record
  changes in the transaction that changes inputs. Beat consumes this durable
  queue; Celery notifications only reduce latency. No count/max-ID snapshots.
- **Common changes are cheap.** New features rewind scans; new resources select
  pairs. Only edits to existing calculation inputs invalidate stored results.
  For those uncommon edits, conservatively reset the dataset or collection.
  Avoid task-version columns and additional billion-row indexes.
- **Fence both processing paths.** Input generations, lease tokens, and the
  existing task claim stamp prevent pre-edit work from landing after an edit.
  Readers suppress invalidated results while reconciliation runs.
- **Short transactions, bounded recovery.** No raster/file I/O or sleeps while
  holding work locks. Synchronous lease commits. Every retry loop must recover
  or expose a diagnosable error without blocking unrelated work.

Reported production state on 2026-10-09: task/result/request/coverage/progress
tables empty, task sequence exhausted, processing workers paused. Recheck at
release time; migration/bootstrap must also handle populated development data.

## 2. Schema and bootstrap

Implement schema in `backend/analytics/migrations/0031_pair_cursor_leases.py`,
with matching models and dependencies on the current features/datasets
migrations. Keep raw SQL in migrations and measured claim/COPY/spatial paths;
use ORM services elsewhere.

1. Adapt #54's bigint migration for `extract_tasks.id`,
   `extract_data.extract_task_id`, and `request_map.task_id`; retain the 1 GiB
   rewrite guard and lock timeout. Raise the identity sequence maximum even
   when column types are already bigint. State: `ExtractTask.id = BigAutoField`.
   Change all task-ID array casts in processing SQL to `bigint[]` (#55).
2. Reorder the NULL-kwargs unique index to
   `(dataset_id, po_id, resource_ids_hash, fm_id) WHERE kwargs IS NULL`.
   Keep full-array equality in probes and keep the kwargs index. Retain
   `extract_tasks_fm_id_idx`; drop `extract_tasks_po_id_idx` and set
   `po.db_index=False`.
3. Reuse `ExtractTaskBuildProgress` as the pair model/table. Add `dataset_id`,
   nullable `bucket date` and `task_group_period`, `current boolean`, and
   `priority int default 0`, nullable `last_error`, and `retry_after` (default
   now). Retain unique `(resource_ids, po_id)`. Add unique
   `(dataset_id, po_id, bucket)` only where `current AND bucket IS NOT NULL`.
   Drop `claimed_at`; cursor becomes non-null, default 0. Pair arrays never change.
4. Add nullable `ExtractTask.pair_id` as a plain bigint without an index or FK.
   Lease-created tasks populate it; request-created tasks may be NULL. This is
   background provenance, not task uniqueness. Pair rows are retained forever
   unless an explicit maintenance operation proves they are unreferenced.
5. Delete `ExtractTaskBuildRun`. Do not add `SyncedCollection` or
   `previous_resource_ids`.

New tables:

| Model/table | Fields beyond the primary key |
|---|---|
| `ExtractTaskLease` / `extract_task_leases`, bigint ID | `progress` FK; `dataset_id`; immutable `resource_ids`, `po_id`, nullable `task_group_period`; `fm_ids int[]`; `input_generations jsonb` (dataset and collection IDs/generations); `token uuid`; `leased_at`, `leased_until`, `retry_after`, `created_at`; `attempts int`; nullable `last_error varchar(100)` |
| `CoverageProgress` / `extract_coverage_progress`, dataset OneToOne PK | `covered_up_to_fm_id int default 0`; `extent_hash text` |
| `ExtractInputState` / `extract_input_state`, composite PK `(kind, object_id)` | `kind` = dataset/collection; `object_id int`; `generation`, `applied_generation` bigints default 0; nullable `rewind_from int`; `sync_pairs`, `reset_tasks`, `reset_coverage`, `bootstrap_pending` booleans default false; `checkpoint jsonb default {}`; `updated_at`, `retry_after`; nullable `last_error` |

Index leases on `leased_until` and `progress_id`. Input states are small; dirty
means `generation != applied_generation`. Document checkpoint keys
`{generation, phase, dataset_id, fm_id, task_id}`. No persistent “sync running”
flag: each chunk uses a row lock, which rollback releases after a crash.
Tombstone states survive source deletion until reconciliation finishes.

**Populated databases:** add pair dataset ID nullable, backfill from
`po.dataset_id`, then enforce NOT NULL. Initially retire all pairs and reset
cursors; derive current sets during bootstrap, avoiding conflicting historical
buckets. Seed input states dirty. Preserve tasks/results/requests. Provide an
idempotent `initialize_extract_work` command for bounded dataset-filtered
backfill of legacy task provenance and pair bucket/period metadata, plus legacy
coverage rebuilding (including status −1). Unknown/obsolete grouped sets get
retired provenance, not NULL/current provenance. Do this while old writers are
stopped and before enabling new readers/workers. Keep long data backfills out
of the schema migration's DDL transaction. Repeated bootstrap must not reset an
already initialized system: migration marks existing dataset states
`bootstrap_pending=True`; command checkpoints per dataset and clears it only
after that dataset's backfill. Ordinary sync cannot clear this flag or publish
a bootstrap-pending scope. New datasets use regular reconciliation.

## 3. Change capture: `analytics/changes.py` and database triggers

Create a permanent state row when a dataset or collection is created; backfill
existing ones. Triggers increment its generation, OR pending flags, retain the
minimum rewind boundary, and invalidate any in-progress checkpoint. Flags stay
set until reconciliation completes. Thus rapid A→B→C changes cannot lose an
earlier reset. New changes clear error/backoff so a repaired configuration is
retried promptly. Ignore writes whose relevant fields are unchanged.

| Source change | Durable action |
|---|---|
| FeatMap insert | Collection rewind from `new.id - 1`; no result reset |
| FeatMap delete | Collection rewind from `old.id - 1`; reconcile missing lease members |
| FeatMap `geom_id`/`fc_id` change | Mark both affected collections; reset tasks/coverage and rewind below affected IDs |
| Feature `shape` change | Mark every referencing collection; reset tasks/coverage; rewind below affected FeatMap IDs |
| Collection active/upload eligibility change | Rewind from collection min ID − 1, including transitions reversed before sync runs |
| Resource insert or temporal/bucket membership change; grouping policy change | Dataset `sync_pairs`; do not reset unchanged arrays |
| Resource delete | Dataset `sync_pairs` and `reset_tasks`; missing-resource tasks become terminal errors |
| Resource path; dataset path/type/mapped; PO function/kwargs/short_name; Mapping values/names | Dataset `reset_tasks` and `sync_pairs`; rewind its pairs to 0 |
| Dataset extent or global/non-global change | Dataset `reset_coverage`, `sync_pairs`; rewind its pairs to 0 |
| Dataset/PO activation or PO creation/deletion | Dataset `sync_pairs`; fence in-flight work; rewind reactivated pairs |
| Titles, citations, descriptions, other display-only metadata | No extraction invalidation |

Use database triggers so ORM bulk writes and direct SQL behave consistently.
Aggregate affected scopes using statement transition tables where practical;
deduplicate collections for shared geometries. Include OLD and NEW owners on
moves and audit cascades. Only input tables have these triggers: task/result
writes do not dirty scopes. Source mutation and change capture commit together.
Owner changes on resources/options/mappings mark both datasets for reset and
pair reconciliation. Prefer retiring/recreating these objects to moving them.
Serialize geometry edits with concurrent FeatMap attachment: lock the Feature
row exclusively before discovering referencing collections; attachment must
participate in that protocol. Cover this ordering in both services and trigger
tests, including deferred FK checks; never rely on a stale join snapshot.

Files have an explicit publication rule: stage replacement content at a new
immutable path, then change the resource path transactionally. Never overwrite
a file workers may be reading. `invalidate_extract_inputs --dataset ID |
--collection ID` records the same durable reset for repair/import workflows;
it cannot make concurrent in-place filesystem writes safe or detect them.

Signals and `BaseIngestCommand` wake `sync_extract_work` using
`transaction.on_commit`, once per ingest rather than once per feature. Failed
notifications lose no work. Beat runs every 60 seconds; each invocation has a
bounded chunk budget. Measure trigger overhead on real bulk ingestion.

## 4. Input fencing and lock order

Implement shared helpers in `analytics/changes.py` for leases, task-row work,
request materialization/finalization, and coverage. Missing state is an
initialization error, never implicitly clean.

- Workers take **FOR SHARE** on relevant clean states in short primary
  transactions and capture generations. This allows concurrent workers but
  conflicts with trigger/sync updates; `FOR KEY SHARE` is insufficient.
- Order: dataset states by ID, collection states by ID, coverage progress by
  dataset, pairs by ID, leases by ID, tasks by `(dataset_id, id)`. Discover
  candidates without locking, acquire guards, then recheck. Use NOWAIT/SKIP
  LOCKED and bounded retries rather than waiting indefinitely with earlier locks.
- The task path's existing advisory claim lock precedes its guards/task locks.
  Sync never acquires it; leases add no global lock. Controlled multi-scope input
  mutations follow the same order; retry database deadlocks at transaction scope.
- Completion requires clean states matching the loaded generations, plus a
  matching lease token or existing task `status=2`/claim timestamp. Dirty inputs
  defer work; they do not create feature failures. No lock survives computation.

Capture a collection-generation map for multi-collection leases. Include guard
wait/hold time and MultiXact overhead in fleet-concurrency benchmarks; this is
one small shared-lock set per page/chunk, never per feature computation.

## 5. Reconciliation: `analytics/sync.py`

`maintenance.sync_extract_work` is tagged `extract.sync`, observed as
`extract_sync`. Each transaction locks one dirty scope, performs one bounded
phase/chunk, checkpoints, and commits. Concurrent syncs skip locked scopes.
Persist errors/timestamps, use `retry_after` to back off failed scopes, and
continue others. Never clear a dirty
generation after processing only part of its repair.

### Pairs: immutable sets

Desired standard pairs contain one resource. Grouped pairs use ascending
resource IDs within UTC `date_trunc(period, temporal)` buckets. Missing temporal
values for grouped resources are visible configuration errors. Remove the
existing `dataset_task_group_period_requires_global` database/model constraint:
coverage now supports grouped non-global datasets.

Under the dataset guard, retire displaced sets before inserting/reactivating
current ones using `(resource_ids, po_id)`. Update bucket/period metadata for an
identical set if necessary. Reset reactivated cursors to 0. Retirement deletes
that pair's leases under lock: this work is obsolete, not abandoned. New pairs
start at 0. Dataset/PO inactivity only parks valid pairs and leases; compute
membership for inactive inputs too, so removal is distinct from a pause.
An empty bucket retires its last pair. A→B→C and A→B→A need no task-array rewrite.

### Existing-input resets

For `reset_tasks`, cover **all kwargs variants and statuses**, one dataset
partition and at most `EXTRACT_RESET_CHUNK_SIZE` tasks per transaction. Dataset
edits cover that dataset; collection edits cover its FeatMaps. Use indexed
feature ranges with `(fm_id, task_id)` continuation, not OFFSET. Explicitly
partition-filter every task/result query, including discovery and joins.

Atomically delete affected `extract_data`, reset status/attempts/error/start/
complete times, and change the claim stamp. Preserve task IDs, RequestMap links,
resource arrays, and priority. Missing-input tasks become terminal −1 with
exhausted attempts. Retired background tasks with valid inputs stay pending but
unclaimable until needed by a request or reactivated; retirement itself must not
exhaust their retry budget. Scope gates block fresh
materialization and completion while reset runs, so inserts cannot evade it.

For `reset_coverage`, delete coverage in bounded chunks: the whole dataset for
extent changes, referenced geometries for collection geometry changes. Shared
geometries mark all their collections. Extent-only edits retain task results:
coverage changes eligibility, not already computed values. Readers honor the
reset flags immediately; old rows are never served while being invalidated.

### Final rewind and publish

After repair phases, one short transaction:

1. Rewind relevant **coverage watermarks and pair cursors** with
   `LEAST(cursor, rewind_from)`. Collection edits apply to all datasets, including
   paused ones; dataset edits to that dataset. Full input/extent resets use 0.
   Missing progress rows start at 0 when needed.
2. Re-token surviving affected leases and expire them; reset attempt budgets for
   changed inputs. Alternatively cancel them only while also rewinding below
   every surviving member. Never silently discard a still-required feature.
3. Set `applied_generation = generation`; clear flags/checkpoint/error/backoff.

Collection finalization locks dataset states in order before its collection
state, then the small progress/pair tables; no task/result scan here. Acquire
those dataset guards in shared mode, its own collection guard exclusively.
Further edits between chunks restart phases with accumulated flags and a new
generation. Initialization uses the same mechanism, without a seed-only bypass.
`rewind_pair_cursors` becomes a wrapper that records durable coverage and pair
rewinds, with dataset/all selectors and a dry run.

## 6. Coverage: `analytics/coverage.py`

Worker slots do one coverage chunk after pending tasks and before a lease.
Lock a clean active non-global dataset's progress with SKIP LOCKED. Within one
transaction and statement timeout, examine the next 5,000 FeatMap rows after
its watermark. Include inactive collections, exclude uploads and dirty scopes;
acquire/recheck input guards before writing. Insert status 0/1 for distinct
geometries using `ST_Contains` and `ON CONFLICT DO NOTHING`. Advance to the last
examined ID, or the observed global maximum on a short scan. Skipped dirty
collections rewind this watermark before becoming clean.

Non-global lease cap = `min(max_fm_id, covered_up_to_fm_id)`. Missing progress
means cap 0. Global→non-global creates progress at 0 and rewinds pairs; the
reverse removes progress and rewinds pairs. Extent hashes are an audit check,
not change delivery. Public coverage queries exclude invalidated scopes.

## 7. Lease path: `analytics/tasks/leases.py`

### Claim

Use primary transactions, synchronous commit, and statement/lock timeouts.
First try one due lease of a current pair and clean active dataset/option,
locking SKIP LOCKED. Refresh input generations and token on every assignment.
Recheck metadata and FeatMap identities; remove deleted members only after
primary confirmation. Retired leases are canceled by sync; paused leases remain
parked and excluded from demand. Lease `retry_after` controls backoff: expiry detects lost
ownership, retry time schedules backoff; takeover requires both to be due.

Otherwise select a current pair below cap with `retry_after <= now()`, ordered by `priority DESC, id`,
locking SKIP LOCKED after input guards. Scan only
`(cursor, min(cursor + SCAN_WINDOW, cap)]`:

- Active, non-upload, clean collections; coverage status 1 for non-global data.
- Exclude exact existing tasks using dataset, PO, hash, full resource array,
  `kwargs IS NULL`, explicit integer-array casts, and the cursor range hint.
- Exclude IDs in outstanding leases of this pair with NOT EXISTS/unnest.
- Order by FeatMap ID; limit to page size. Discover collection guards first,
  then lock/recheck before the final scan; restart if the required scope set
  changes. Do not acquire pair/lease locks before newly discovered guards.
- Insert lease and advance cursor atomically: last ID for a full page,
  scan-window end otherwise. At most 10 empty windows per invocation, then yield.

Dirty scopes can be skipped because their rewind is durable. Request tasks win
uniqueness conflicts. Verify full-array equality on conflicting hash keys at
claim/completion: a different array is a visible pair error, not success.
Persist such an error/backoff on the pair and retain the work; never advance
past it. A completion collision retains its lease and backs off that pair too.

### Load and compute

Load PO, ordered resources, and category mapping once; WKB geometries in blocks.
**Do not filter already-leased IDs by collection activity.** Finishing previously
claimed work for an inactive collection is harmless cache work. Generations
still fence edits. Replica-missing IDs are retried on primary; confirmed
deletions are omitted, other missing inputs become explicit errors.

Replica loading defaults off. Obtain a WAL barrier on primary **after** claim
commit, poll in autocommit, then use short read-only metadata/block transactions.
No transaction spans processing blocks. Fall back to primary on timeout or
recovery conflicts; tag all connection aliases.

Compute block-major/resource-minor; batch processors open each raster once per
block. Buffer outcomes for the page. Feature/resource exceptions produce −1
outcomes for bounded task retries. Check stop/deadline between features,
including inside batch generators. Long native calls may require termination;
expiry recovers the lease afterward.

### Complete

One transaction:

1. Acquire input guards, lock lease, recheck token/generations/current pair and
   active dataset/PO. Stale token: discard. Dirty generation: defer/reconcile.
   Inactive dataset/PO: park. Never modify a lease after losing its token.
2. Bulk INSERT terminal tasks, all required columns and `pair_id`, with
   `ON CONFLICT DO NOTHING RETURNING id, fm_id` on the NULL-kwargs unique key.
   Check full-array equality to distinguish request conflicts from hash collisions.
3. COPY results only for returned IDs using `_COPY_RESULTS` inside
   `wrap_database_errors`, then delete lease. Tasks/results commit together.
   Ordinary failures record attempts consistently with one execution.

Retry OperationalError/InterfaceError three times with backoff, rerunning the
whole transaction. A missing lease on retry requires no further write, whether
it committed or was canceled. SQLSTATE 22001/22003/22P02/22021 or client dump
errors trigger a fenced retry with per-feature savepoints: unstoreable features
become −1 without rows. Other errors roll back the page. Metrics count commits.

## 8. Recovery and sizing

- Start with **256-feature pages**, 256-feature geometry blocks, 30-minute
  leases, no heartbeat. The previous 2,000-feature proposal is a benchmark
  candidate; measure grouped/vector workloads before adopting it. Keep page p99
  well below lease duration and request-latency limits before increasing size.
- On the third unsuccessful assignment, split a multi-feature lease atomically.
  Children get fresh retry budgets; assign one now and queue the other. Repeat
  until isolated. A singleton gets its own configured number of assignments
  before becoming terminal −1 with exhausted attempts. Parent failures do not
  consume a child's attempts. Takeover/terminal writes use normal input fencing.
- Permanent setup errors (missing resource, invalid processor/kwargs) produce
  explicit failed tasks. Unexpected repeatable Python exceptions consume
  attempts and back off. Infrastructure failures back off exponentially with
  jitter, capped at five minutes, remain recoverable, and alert on age; they do
  not poison individual features. Due-work selection lets other pairs proceed.
- SIGTERM stops claims. Finish within the drain deadline or return the page,
  changing token and setting immediate expiry; refund this assignment once.
  Hard death uses expiry. An expired token can still complete until takeover
  changes it. Dataset pauses do not consume attempts.

## 9. Task path, requests, and readers

Factor `_result_rows` and `_op_kwargs` from `processing.py`. Add input generation
capture/rechecks to load and `_persist_outcomes`, retaining claim-stamp fencing.
Claims skip dirty scopes and obsolete background pairs unless RequestMap still
requires the task. Preserve priority. Discover tasks first, take guards before
task locks, recheck, and release stale claims through existing fenced helpers.

`services._build_tasks` retains singleton resource tasks; request grouping is
unchanged. Identical singleton lease tasks are reusable. Defer dirty-input
materialization through the existing pending request/redispatch mechanism,
without marking a user error or waiting under a request lock. If requested
features/resources were deleted, report that explicitly; missing RequestMap
rows after a cascade must not turn a partial request into successful output.

Update visualization, merge, readiness checks, and coverage readers together:

- Live results require `status=1` and no pending `reset_tasks` on their dataset
  or collection. Coverage honors `reset_coverage`. Addition/activation-only
  dirtiness need not hide unchanged existing results.
- Explore includes grouped results only from current pairs, via `pair_id` and
  the small pair table. Backfill legacy grouped provenance before switching.
  Deduplicate logical result cells when both a current grouped task and a
  singleton request task exist; prefer the current pair's completed result.
  RequestMap views may show retired sets while their inputs/results remain
  valid. Resource arrays never change underneath those values.
- Output builds capture clean input generations before merging and recheck
  under shared guards before successful finalization. Mismatch discards staged
  output and requeues. Keep file construction outside DB transactions and
  preserve existing request heartbeat/claim fencing. Do not expose a staged
  file until generation-checked finalization succeeds; audit rename/download
  visibility accordingly. Completed downloads remain historical snapshots,
  with no automatic rebuilding of old artifacts.

## 10. Worker, processors, configuration

`extract_worker.run_chunk`: pending tasks → one coverage chunk → lease → jittered
idle wait. Preserve per-slot process isolation, record lease `_chunk_starts`,
close all connection aliases, and keep backoff stop-aware. Reconciliation runs
on background workers so processing cannot starve it.

| Setting | Default |
|---|---|
| `EXTRACT_TASK_LEASES_ENABLED` | True; off stops assignments, existing leases may drain |
| `EXTRACT_TASK_LEASE_PAGE_SIZE` | 256 |
| `EXTRACT_TASK_LEASE_BLOCK_SIZE` | 256 |
| `EXTRACT_TASK_LEASE_SECONDS` | 1800 |
| `EXTRACT_TASK_LEASE_SCAN_WINDOW` | 100000 |
| `EXTRACT_TASK_LEASE_BISECT_ATTEMPT` | 3 |
| `EXTRACT_TASK_LEASE_READ_REPLICA` | False |
| `EXTRACT_TASK_LEASE_REPLICA_WAIT_SECONDS` | 2.0 |
| `EXTRACT_WORKER_DRAIN_SECONDS` | 840 |
| `EXTRACT_COVERAGE_CHUNK_SIZE` | 5000 |
| `EXTRACT_RESET_CHUNK_SIZE` | 5000 tasks; independently bound coverage deletes |
| `EXTRACT_SYNC_INTERVAL_SECONDS` | 60 |
| `EXTRACT_SYNC_CHUNKS_PER_RUN` | 20 |

Validate positive limits/block sizing. No lease async-commit setting initially.
Compose/Helm termination grace must exceed drain time plus a margin.

Add `BATCH_REGISTRY` for the six rasterstats functions. Preserve alignment and
scalar/array/nodata semantics. Restart a failed generator after the bad feature;
distinguish resource-open errors from geometry failures. Two consecutive open
failures fail the remaining block. Vector processors retain per-feature calls.

Remove builder command/run model, old coverage tasks/command, builder worker/
dispatcher, sweep, and `trigger_coverage_and_extract`. Replace beat entries with
sync; retain task/request reapers and error retry management. Remove
`N_EXTRACT_TASK_BUILDERS`/`EXTRACT_TASK_BUILD_*`; register Celery tasks through
`tasks/__init__.py` and replace builder job labels with `extract_sync`.

## 11. Demand and observability

`extract_work_demand() RETURNS bigint STABLE` sums eligible pending tasks,
cardinality of **all** runnable outstanding leases, positive unscanned pair
ranges, and uncovered ranges. Count active clean scopes/current pairs; omit
parked/retired work. Unexpired leases keep the final running pages represented.
Ranges overestimate with ID gaps; measure query cost and calibrate KEDA's target.
Dirty scopes recover independently through beat/background workers. Preserve
pending-index use rather than introducing an unindexed billion-row count.

Expose lease and dirty-state health: outstanding/expired/parked counts, oldest
age, max attempts, checkpoint, error, retry time. Metrics cover page outcomes,
takeovers/splits, error classes, claim/load/compute/commit times, replica fallback,
guard wait/hold, coverage chunks, sync/reset/rewind chunks, and recovery age.
Bulk-count tasks, amortize timings, and avoid feature/pair ID metric labels.

## 12. Tests and acceptance

Use threaded `TransactionTestCase` with barriers, not sleeps, for races. Keep
reusable raster/feature/partition/EXPLAIN helpers when removing builder tests.

- **Schema/bootstrap:** fresh/populated DB, bigint past int32, historical grouped
  sets, provenance, interrupted/repeated bootstrap, legacy coverage −1, state drift.
- **Capture:** ORM/bulk/raw SQL, rollback, deletions/cascades, same-value writes,
  shared geometry, moves, immutable file publication, no per-feature dispatch.
- **Late commits:** allocate 101, commit/process 102 first, then commit 101;
  prove pair and coverage recovery. Repeat for new/inactive collections,
  replacement with unchanged count, initialization, and missed Celery messages.
- **Sync:** interruption, concurrent syncs, edit mid-reset, retained flags/minimum,
  bounded transactions, dirty-scope fairness, no early acknowledgement. Edits
  during lease/task claim/load/flush and request merge/finalization.
- **Resources:** A→B→C/A→B→A, empty buckets, temporal moves, missing resources,
  grouped non-global, pauses/reactivation, singleton conflicts, no relabeling,
  retired Explore results, pending tasks still referenced by requests.
- **Coverage:** extent/global transitions, geometry replacement, uploads/shared
  geometry, cap 0 without progress, concurrent scan/reset/rewind.
- **Leases:** no overlap after rewind, cap/windows, rollback, stale token/input,
  brief inactive interval, confirmed deletion versus replica lag, request/hash
  conflicts, lost commit, COPY savepoint isolation.
- **Recovery/readers:** death at each stage, child retry budgets, singleton
  exhaustion, bad setup versus outage, drain/hard kill, no stale values during
  reset, failed-task filtering, request output requeue, historical downloads.
- **Performance:** EXPLAIN probes/completion/reset/materialization/demand;
  pruning and bounded query count; batch equivalence; page memory/runtime;
  guard contention and trigger overhead at expected concurrency.

```bash
docker compose exec backend uv run python manage.py makemigrations --check
docker compose exec backend uv run python manage.py migrate
docker compose exec backend uv run python manage.py test analytics datasets features public_api visualize
```

End-to-end: ingest global/non-global/grouped data and boundaries; confirm demand
drains, coverage gates work, and lease results equal task-row results. Submit a
request during a lease, edit geometry mid-compute, add/remove a month, reactivate
a collection, interrupt sync, and kill/restart workers. Verify eventual recovery
and no stale published values. Compare old/new paths with equal durability,
data, and concurrency: throughput, WAL/task, pool occupancy, memory, page p99,
request wait, and mutation-to-recovery time. Tune page size from those results.

## 13. Documentation and release

During implementation, update database guidance for cursor/input-state contracts,
immutable pairs, recovery, bigint, and demand; correct stale builder/coverage
references and code docstrings. Update the design document's status/deviations.
Do not claim measured speedups before the comparison above.

Release requires separate explicit permission; this plan executes nothing.

1. Recheck sizes/sequence; drain processing **and old builder/coverage jobs**.
   Stop old beat dispatch. Old containers must not use the new schema. Preserve
   requests; no production truncate is prescribed by this plan.
2. Migrate, then run bootstrap/initial reconciliation with assignments disabled.
   Verify triggers, provenance, reader filters, registered tasks, and dirty-state
   recovery; start new background workers/beat before processing workers.
3. Coordinate Helm: KEDA query/target, optional worker `PG_RO_*`, settings,
   builder removals, termination grace. Inspect actual chart revision; the
   previously noted local 0.51.1 may be stale.
4. Enable a small processing fleet, fault-test, then expand. Kill switch stops
   new leases while requests/reconciliation continue. Old-builder image rollback
   is unsupported after migration; use assignments disabled and a forward fix.
5. Supersede #54/#55 once their bigint behavior is covered. Review #53's scope
   before closing; #44 (new dataset partitions) remains independent.
