# Extraction Workflow

How extraction work flows through GeoQuery: which tables hold it, how input
changes are recorded and reconciled, and what one processing worker slot does
from claiming work to committing results.

Background extraction uses **pair cursor leases**: task rows are created only
when work finishes. Requests and retries still use pre-created task rows. Both
run in the same worker loop.

Code references are to files under `backend/`.

- [Part 1 — Vocabulary](#part-1-vocabulary)
- [Part 2 — The tables](#part-2-the-tables)
- [Part 3 — How input changes get in](#part-3-how-input-changes-get-in)
- [Part 4 — One worker slot, step by step](#part-4-one-worker-slot-step-by-step)
- [Example: a new boundary collection is ingested](#example-a-new-boundary-collection-is-ingested)

---

## Part 1 — Vocabulary

### Work and results

| Term | Meaning |
|---|---|
| **Feature** | A boundary in a feature collection: a `feat_map` row (its id, the **fm_id**), pointing at a geometry in `features`. Work is always per feature. |
| **Collection** | A `feature_collections` row, such as an ADM2 boundary set. User-uploaded collections (`is_user_upload`) are only used by requests, never by background work. |
| **Pair** | One fixed, ordered set of resources (`resource_ids`) plus one processing option. Standard datasets have one resource per pair. Grouped datasets have one pair per time bucket, for example 12 monthly rasters for one year. A pair's array never changes. |
| **Current / retired pair** | `current = true` means the pair is still wanted. When the set of resources changes, sync **retires** the old pair rather than editing it. Retired pairs are kept so old results can still be identified. |
| **Task row** | One `extract_tasks` row: one pair (or request-specific resources and options) applied to one feature. Status 0 is pending, 2 running, 1 done and -1 failed. |
| **Result row** | One `extract_data` row: one named value for one task. Most tasks have one; categorical datasets have one per class. |
| **Task-row path** | The older way of working: a task row exists *before* it's computed, and is claimed, run and updated. Requests, retries and request tasks that sync reset still use it. |
| **Lease path** | Background work. No task row exists until the work is finished. |

### Cursors and leases

| Term | Meaning |
|---|---|
| **Cursor** (`cursor_fm_id`) | Per pair: how far through the fm_ids this pair has **accounted for**. Every eligible feature below it has a task row, is in an outstanding lease, or is covered by a pending rewind. It does *not* mean "finished". |
| **Cap** | The highest fm_id a pair may scan up to: `extract_eligible_max_fm_id()`, the highest fm_id in any non-upload collection. For a non-global dataset it's also limited by that dataset's coverage watermark. |
| **Window** | One scan of up to `EXTRACT_TASK_LEASE_SCAN_WINDOW` (100,000) id positions after the cursor, within one transaction. |
| **Page** | The features one lease covers: at most `EXTRACT_TASK_LEASE_PAGE_SIZE` (256), and fewer for slow pairs. |
| **Block** | A slice of a page (`EXTRACT_TASK_LEASE_BLOCK_SIZE`, 256 features) whose geometries are loaded together during computation. |
| **Lease** | A row in `extract_task_leases` saying "this worker is computing these features for this pair until `leased_until`". |
| **Token** | A random UUID on each lease, changed whenever ownership changes. A worker can only finish a lease whose token still matches the one it was given. |
| **Expired / due** | **Expired:** `leased_until` has passed, so the owner is presumed gone. **Due:** expired, with its `retry_after` backoff also passed, so another worker may **take it over**. |
| **Attempts** | How many times a lease has been assigned without finishing. `EXTRACT_TASK_LEASE_BISECT_ATTEMPT` (3) on a multi-feature page splits it in half. `MAX_EXTRACT_TASK_ATTEMPTS` (5) on a single feature records it as a terminal failed task. |
| **Pace** | `seconds_per_feature`: a moving average per pair, used to size its pages. |
| **Parked** | The lease's dataset or processing option was deactivated. The lease waits, without counting an attempt, until they're active again. |

### Coverage

| Term | Meaning |
|---|---|
| **Global / non-global dataset** | A **global** dataset covers every feature. A **non-global** one only covers features whose geometry falls inside its `spatial_extent`. |
| **Coverage row** | `coverage (geom_id, dataset_id, status)`, status 1 inside the extent and 0 outside. It's a cached `ST_Contains` result. It belongs to a geometry, not to a feature or collection. |
| **Watermark** | `covered_up_to_fm_id` in `extract_coverage_progress`, per non-global dataset. Every feature at or below it has a coverage answer, so lease scans for that dataset can't go past it. |

### Input change tracking

| Term | Meaning |
|---|---|
| **Scope** | One `extract_input_state` row, either a dataset (`kind='dataset'`) or a collection. Every change to an input is recorded against one or more scopes. |
| **Generation** | Goes up by 1 on *every* recorded change to a scope. A scope is **dirty** while `generation ≠ applied_generation`, meaning sync still has work to do. |
| **Epoch** | Goes up only on an **invalidating** change: one that makes stored results or in-flight work wrong. Work records the epochs it started under, and checks them again before writing. Additive changes, like a new feature or resource, don't move it. |
| **Available / unavailable** | A scope is unavailable while `reset_tasks`, `reset_coverage` or `bootstrap_pending` is set (`UNAVAILABLE_SQL` in `analytics/changes.py`), or while another transaction holds its row exclusively. No new work starts on an unavailable scope. |
| **Rewind** (`rewind_from`) | A durable request recorded on a scope: "when this is published, move cursors and watermarks back to this fm_id". If several changes ask, the lowest value is kept. |
| **Targeted invalidation** | An `extract_invalid_items` row naming one resource, option or feature whose tasks must be reset, without taking the whole scope offline. |
| **Sync** | The background Celery task that works through dirty scopes (`analytics/sync.py`). |
| **Publish** | Sync's final step for a scope: apply rewinds, re-token affected leases, clear the targeted items, and mark the scope clean. |
| **Barrier** | During a scan, the first feature the scan may not pass, because its collection is locked by a writer or being reset below its rewind point. |

### Locks and transactions

| Term | Meaning |
|---|---|
| **Share-lock** (`FOR SHARE`) | A row lock that **many transactions can hold at once**. It stops anyone from *updating* that row until they all commit. Workers share-lock the input state rows they rely on, so no trigger or sync can change those scopes mid-step. |
| **Exclusive lock** (`FOR UPDATE`, or an `UPDATE`) | A row lock only one transaction can hold. Triggers and sync take these on state rows, and workers take them on pair and lease rows. |
| **SKIP LOCKED** | "If someone else holds the row, act as if it isn't there; don't wait." Workers use it everywhere, so a long ingest holding a state row never makes the fleet queue up. |
| **Advisory lock** | An application-defined lock on a number. The task-row claim takes `pg_advisory_xact_lock(CLAIM_LOCK_ID)` so task-row claims run one at a time. |
| **Lock timeout / statement timeout** | Upper bounds on waiting for a lock and on running a statement. Leases use 5 s and 60 s, coverage 2 s and 2 min, sync 5 s and 5 min. |
| **Synchronous commit** | The commit returns only after the WAL is flushed to disk. Lease completion uses it; the task-row path defaults to asynchronous (`EXTRACT_TASK_SYNCHRONOUS_COMMIT`). |

---

## Part 2 — The tables

### Inputs (watched by triggers)

| Table | What matters for extraction |
|---|---|
| `datasets` | `path`, `type`, `mapped`, `is_global`, `spatial_extent`, `active`, `task_group_period` (grouping) |
| `dataset_resources` | one raster per row: `path`, `temporal` (decides grouped buckets), `dataset_id` |
| `processing_options` | `function`, `kwargs`, `short_name`, `active`, `dataset_id` |
| `mappings` | category value→name maps, used by mapped datasets |
| `feature_collections` | `active`, `is_user_upload` |
| `feat_map` | features: `id` (the fm_id), `fc_id`, `geom_id` |
| `features` | geometries: `shape` |

### Work and results

| Table | Role | Written by |
|---|---|---|
| `extract_tasks` | Task rows, partitioned by dataset. **`pair_id`** records which pair a background task came from, with no index or foreign key. The no-kwargs unique index is **`(dataset_id, po_id, resource_ids_hash, fm_id) WHERE kwargs IS NULL`**, which both the "task already exists?" check and the insert's `ON CONFLICT` use. | Lease completion (status 1 or -1), request materialization (status 0), task-row flushes, sync resets |
| `extract_data` | Result rows, partitioned by dataset | Lease completion (COPY), task-row flush; deleted by sync resets |
| `request_map` | Links requests to their task rows | Request materialization |

### Lease machinery

| Table | Key columns | Role |
|---|---|---|
| `extract_task_build_progress` (**pairs**) | `resource_ids`, `po_id`, `dataset_id`, `bucket`, `current`, `priority`, **`cursor_fm_id`**, `seconds_per_feature`, `last_error`, `retry_after` | One row per pair, unique on `(resource_ids, po_id)`. The old builder's table, reused. |
| `extract_task_leases` | `progress_id` (the pair), `dataset_id`, `resource_ids`, `po_id`, **`fm_ids int[]`**, **`token`**, **`input_generations`** (epochs, JSON), `leased_at`, **`leased_until`**, `retry_after`, **`attempts`**, `last_error` | Outstanding pages. Hundreds of rows, not billions. |
| `extract_coverage_progress` | `dataset_id` (primary key), **`covered_up_to_fm_id`**, `extent_hash` | One watermark per non-global dataset |
| `coverage` | `(geom_id, dataset_id)`, `status` 0/1 | Cached containment answers |

### Change tracking

| Table | Key columns | Role |
|---|---|---|
| `extract_input_state` | `(kind, object_id)`, **`generation`**, **`applied_generation`**, **`epoch`**, **`rewind_from`**, flags `sync_pairs` / `reset_tasks` / `reset_coverage` / `bootstrap_pending`, `checkpoint` (JSON), `retry_after`, `last_error` | One row per dataset and per collection: a durable record of changes not yet processed, and the row workers share-lock |
| `extract_invalid_items` | `(scope_kind, scope_id, item_kind, item_id)`, where the item is a `resource`, `option` or `feature` | Targeted invalidations, deleted at publish |

### Shared SQL definitions (migration `analytics/0031_pair_cursor_leases`)

| Name | What it is |
|---|---|
| `extract_input_mark(...)` | The one function every trigger uses to record a change. It increments generation, increments epoch if invalidating, ORs the flags, keeps the lowest rewind, clears the checkpoint and any error backoff, and creates the row if it's missing. |
| `extract_input_items(...)` | Inserts targeted invalidation rows |
| `extract_valid_tasks` (view) | Tasks whose stored results can be trusted: not in a dataset being reset or bootstrapped, and not named by a targeted invalidation |
| `extract_runnable_tasks` (view) | Valid pending tasks that a task-row claim may take: inputs active and available, and belonging to a current pair, having no pair, or linked to a request |
| `extract_eligible_max_fm_id()` | The cap: the highest fm_id in a non-upload collection |
| `extract_work_demand()` | The autoscaler's demand estimate: runnable tasks + features in outstanding leases + unscanned cursor ranges + uncovered ranges |

---

## Part 3 — How input changes get in

This runs *alongside* the workers and decides what they're allowed to do.

### Step 1: the trigger records the change, in the same transaction

Every watched table has `AFTER INSERT / UPDATE / DELETE … FOR EACH STATEMENT`
triggers that use transition tables. A bulk insert of a million features fires
**once per statement**, not once per row.

Each trigger calls `extract_input_mark` on the affected scopes. Because it runs
inside the transaction that made the change, the change and its record commit
together or not at all. That holds for Django saves, bulk writes and raw SQL
alike.

| Change | Scope marked | Generation | Epoch | Flags / rewind / items |
|---|---|---|---|---|
| Dataset created | dataset | +1 | — | `sync_pairs`, rewind 0 |
| Dataset `path`/`type`/`mapped` changed | dataset | +1 | +1 | `sync_pairs`, `reset_tasks`, rewind 0 |
| Dataset extent or `is_global` changed | dataset | +1 | +1 | `sync_pairs`, `reset_coverage`, rewind 0 |
| Dataset `active` or grouping changed | dataset | +1 | — | `sync_pairs` |
| Dataset deleted | dataset | +1 | +1 | all three flags; the row stays as a tombstone until sync finishes |
| Resource added, or its `temporal` changed | its dataset | +1 | — | `sync_pairs` |
| Resource `path` changed | its dataset | +1 | +1 | item `resource` |
| Resource deleted | its dataset | +1 | +1 | `sync_pairs`, item `resource` |
| Option added, deleted or (de)activated | its dataset | +1 | — | `sync_pairs` |
| Option `function`/`kwargs`/`short_name` changed | its dataset | +1 | +1 | item `option` |
| Resource or option moved to another dataset | both datasets | +1 | +1 | `sync_pairs`, `reset_tasks`, rewind 0 |
| Category map changed (mapped datasets only) | dataset | +1 | +1 | `sync_pairs`, `reset_tasks`, rewind 0 |
| Collection created | collection | state row created, clean | — | — |
| Collection `active` or upload flag changed | collection | +1 | — | rewind to (its lowest fm_id − 1) |
| Feature added (non-upload) | its collection | +1 | — | rewind to (lowest new fm_id − 1). Also share-locks the geometry. |
| Feature deleted (non-upload) | its collection | +1 | +1 | rewind |
| Feature moved, or pointed at a different geometry | old and new collections | +1 | +1 | rewind the new collection. A new geometry also logs item `feature`. |
| Geometry `shape` changed | every collection using it | +1 | +1 | rewind, item `feature` for each referencing feature, **and that geometry's coverage rows are deleted right there** |
| Titles, names, attributes, citations | — | — | — | nothing |

Raster files must be published at a new path and the resource's `path`
updated. The triggers can't see a file rewritten in place. For changes made
outside the watched tables, `manage.py invalidate_extract_inputs` records the
same kind of reset by hand.

### Step 2: a signal or beat wakes sync

The state row is the durable record. Messages only make sync start sooner:

- **Django signals** (`analytics/signals.py`): saving or deleting a `Dataset`,
  `DatasetResource`, `Mapping`, `ProcessingOption` or `FeatureCollection`
  calls `wake_sync()`.
- **`BaseIngestCommand`** calls `wake_sync()` once after an ingest. Feature
  and `feat_map` writes deliberately have no signal, so a million-feature
  ingest sends one message, not a million.
- **`wake_sync()`** (`analytics/changes.py`) sends at most one Celery message
  per transaction, *after* commit.
- **Beat** runs `sync_extract_work` every `EXTRACT_SYNC_INTERVAL_SECONDS` (60)
  regardless, so a lost message only costs latency.

### Step 3: sync works through dirty scopes

`sync_extract_work` runs on the **background workers**, not the processing
workers, so a busy processing fleet can't starve it. Each run handles up to
`EXTRACT_SYNC_CHUNKS_PER_RUN` (20) chunks, rotating through the due scopes so
one huge reset can't block others.

**Each chunk is one transaction:**

1. **Lock the scope's state row exclusively**, with `FOR UPDATE SKIP LOCKED`.
   If a worker holds a share-lock, or another sync holds it, the scope is
   skipped until next time.
2. **Run the next bounded piece** of the next phase.
3. **Save a checkpoint** and commit.

If a new change arrives in the middle, `extract_input_mark` clears the
checkpoint and the phases restart, keeping all the flags accumulated so far.
A phase that raises sets `last_error` on the scope and backs it off
exponentially; the other scopes continue.

**Dataset phases**, run only when the scope's flags or items call for them:

1. **`pairs`** (`reconcile_pairs`): compute the desired pairs, meaning every
   resource set × every option, active or not. Retire pairs that are no longer
   desired and delete their leases. Insert new pairs, or reactivate old ones
   with the cursor at 0. A grouped resource with no date is a configuration
   error shown on the scope.
2. **`reset_tasks`**: every task in the dataset's partition,
   `EXTRACT_RESET_CHUNK_SIZE` (5,000) per chunk.
3. **`reset_items`**: only tasks of the logged resources and options, walked
   through the pair index.
4. **`reset_coverage`**: delete the dataset's coverage rows, 5,000 per chunk.
5. **`publish`**.

**Collection phases:** `reset_items`, which covers the logged features in each
partition, then `reset_coverage`, which only `invalidate_extract_inputs` sets,
then `publish`.

**What a reset does to each task:**

- its `extract_data` rows are deleted;
- **if no request links it, the task row is deleted too.** A lease will
  recompute it after the rewind;
- **if a request links it,** it keeps its id and links, goes back to status 0
  with attempts at 0, and gets a new claim stamp. If one of its resources no
  longer exists, it becomes -1 with no retries left instead.

Datasets seeded by migration 0031 start `bootstrap_pending`; ordinary sync
leaves them alone until `manage.py initialize_extract_work` has finished them.

### Step 4: publish

**For a dataset** (`_publish_dataset`):

- **Coverage watermark:** non-global datasets get one, created at 0 or lowered
  to `rewind_from`. Global datasets have it deleted.
- **Pair cursors** above `rewind_from` are lowered to it.
- **Targeted items:** the current pairs that use a logged resource or option
  go back to cursor 0.
- **If any reset or item was involved**, every lease of the dataset is
  **re-tokened and expired**: new token, due now, attempts reset to 0. Purely
  additive changes leave leases alone.

**For a collection** (`_publish_collection`):

- **Lock first:** every watermark and every current pair, *across all
  datasets*.
- **Then lower** those above `rewind_from`. Locking all of them before
  comparing catches a lease claim or coverage chunk that was about to move
  past the rewind point.
- **Leases with a deleted or invalidated feature:** deleted features are
  removed from them, and they're re-tokened. Leases left empty are deleted.

**Then, for either kind:** delete the scope's targeted items, and set
`applied_generation = generation` with all flags cleared. For a source that
was deleted, the state row itself is removed.

---

## Part 4 — One worker slot, step by step

### 0. Process model

`run_extract_worker` starts an `ExtractWorker` (`analytics/extract_worker.py`)
with N **slots**. Each slot is a separate process, so a GDAL crash or OOM kill
takes out only that slot, which is then replaced. A slot's process is recycled
after a set number of units to reclaim memory.

Each slot repeatedly calls `run_chunk`:

```
1. task-row chunk        (requests, retries, reset request tasks)
2. only if (1) claimed nothing and nothing failed:
     a. one coverage chunk   (non-global datasets)
     b. one lease page       (background work)
3. close every DB connection, so no pooler slot is held between units
4. wait about EXTRACT_WORKER_IDLE_SECONDS (60) ±25% if nothing was done;
   back off 5 s → 300 s (±25%) after a DB failure
```

### 1. Task-row chunk

`claim_pending_tasks` (`analytics/tasks/processing.py`), in one transaction:

1. Take the **advisory lock**. Task-row claims across the fleet run one at a
   time.
2. **Find candidate datasets:** active, with an available state row.
3. **Find candidate tasks** from `extract_runnable_tasks`, in order of
   priority, then submit time, then id.
4. **Share-lock** those tasks' dataset and collection state rows, and recheck.
   Rows locked by a writer are skipped.
5. Set the chosen rows to **status 2** with a fresh `update_time`, the
   **claim stamp**.

Outside the transaction, each task is computed. Its inputs are loaded with
their epochs recorded. Then the **flush** writes every outcome together, only
if each row is still status 2 with the same claim stamp and its epochs haven't
changed. Tasks the slot didn't start are released back to pending.

Background work reaches this path only as failures. A lease writes a failed
feature as a status -1 task row. The error sweep returns it to pending while
it has attempts left, and a later claim retries it here.

### 2. Coverage chunk

`run_coverage_chunk` (`analytics/coverage.py`):

1. **Candidates:** up to 8 non-global datasets that are active, available,
   and have a watermark below the cap.
2. **For the first one that works, in one transaction:**
    1. **Share-lock** its dataset state row (skip if unavailable).
    2. **Lock its watermark row** exclusively, skipping it if another slot
       holds it.
    3. **Read the next `EXTRACT_COVERAGE_CHUNK_SIZE` (5,000) `feat_map` rows**
       above the watermark, in id order.
    4. **Share-lock their collections' state rows**, skipping locked ones, and
       compute the **barrier** (`barrier_for`):
        - **a writer holds the collection's state row:** stop before that
          collection's first feature;
        - **the collection is being reset as a whole:** it may be passed only
          above its `rewind_from`, because publishing will rewind the
          watermark there anyway. Otherwise stop;
        - **only additive changes pending:** pass through normally.
    5. **Insert coverage rows** (`ST_Contains` → 1 or 0) for each distinct
       geometry below the barrier, skipping uploads and unavailable
       collections.
    6. **Move the watermark** to the last row examined, or to just below the
       barrier.

### 3. Claiming a lease

`claim_lease` (`analytics/tasks/leases.py`) returns nothing if
`EXTRACT_TASK_LEASES_ENABLED` is off. Otherwise it **takes over a due lease
first**, and only then leases a new page.

#### 3a. Taking over a due lease

**Find up to 16 due leases** whose:

- pair is current;
- dataset and option are active;
- dataset state is available;
- pair's resources, option and features aren't named by a targeted
  invalidation.

Shuffle them so slots don't all reach for the same one. Then, in one
transaction:

1. **Share-lock** the dataset's state and the state of each member feature's
   collection. Stop if any is unavailable.
2. **Lock the lease row** exclusively, skipping it if locked. Confirm it's
   still due and has the same members.
3. **Re-read the members on the primary**, now that the guards are held:
    - **A feature moved to an unguarded collection:** give up for now.
    - **Features deleted:** drop them.
    - **None left:** delete the lease.
4. **Decide the page's fate:**
    - **One feature with attempts ≥ 5:** insert it as a status -1 task with no
      retries left (a request's existing task wins the conflict), and delete
      the lease.
    - **Several features with attempts ≥ 3:** split it. The first half stays
      here. The second half becomes a new lease, due now, with attempts 0.
    - **More features than the pair's pace allows:** cut it to the right size,
      with no penalty.
5. **Reassign:** new token, `leased_until = now + EXTRACT_TASK_LEASE_SECONDS`
   (1,800 s), `attempts + 1`, and `input_generations` = the epochs just read
   under the share-locks.

#### 3b. Leasing a new page

1. **Read the cap**, `extract_eligible_max_fm_id()`.
2. **Find up to 64 candidate pairs**, ordered by `priority DESC, id`. A
   candidate:
    - is current, and past its `retry_after` backoff;
    - has an active dataset and option, and an available dataset state;
    - isn't named by a targeted invalidation;
    - has its cursor below its cap. For a non-global dataset the cap is
      limited by the watermark, and no watermark means no work.
3. **For each pair, scan up to 10 empty windows** before trying the next pair.

**`_scan_window`**, one transaction with a 60 s statement timeout and 5 s lock
timeout:

1. **Share-lock the dataset's state row.** Skip the pair if the dataset is
   unavailable.
2. **Lock the pair row** exclusively, skipping it if locked, and read its
   cursor, the watermark, `is_global` and its pace. The order matters: a
   collection publish locks every current pair before lowering cursors.
   Because the scan holds the pair first, the publish either waits for this
   scan to commit and then lowers the cursor, or has already committed and the
   scan sees the lowered value.
3. **Set the window** to `(cursor, min(cursor + scan window, cap)]`.
4. **Find the collections that have features in the window**, share-lock their
   state rows (skipping locked ones), and compute the **barrier**, as in
   coverage. The window ends just below it.
5. **Collect this pair's outstanding lease members** within the window.
6. **Run the page query** (`_PAGE_SQL`), keeping features that:
    - are in an available, active, non-upload collection;
    - aren't named by a targeted invalidation;
    - have coverage status 1, for non-global datasets only;
    - aren't already in an outstanding lease of this pair;
    - have **no task row** with the same dataset, option, hash, fm_id, null
      kwargs and full resource array. This lookup uses the unique index.

    The query is ordered by fm_id and limited to the **page size**:
    `EXTRACT_TASK_LEASE_PAGE_SECONDS` (60 s) ÷ pace, never more than a
    quarter of the lease, capped at `EXTRACT_TASK_LEASE_PAGE_SIZE` (256).
    With no pace yet, it's the cap ÷ the number of resources, so 21 for a
    12-month bucket. A slot only looks for request tasks between units, so
    this bounds how long a new request waits behind background work.
7. **Check for hash collisions.** If the 32-bit hash points to a task with a
   *different* array, nothing is leased, the cursor stays put, and the pair
   gets `last_error` and a 300 s `retry_after`.
8. **Move the cursor** to the last fm_id leased if the page is full, or to the
   end of the window if not.
9. **Insert the lease** with `fm_ids`, a new token, `input_generations` (the
   epochs read under the share-locks), `leased_until = now + 1,800 s` and
   `attempts = 1`. With nothing to lease, commit just the cursor move. That's
   an **empty window**, and the claim scans the next one.

The lease and the cursor move commit together, so if the transaction rolls
back neither happened.

### 4. Load

No transaction or lock is held from here until completion.

**Reads go to the primary by default.** If `EXTRACT_TASK_LEASE_READ_REPLICA`
is on, the worker records the primary's current WAL position, waits up to
`EXTRACT_TASK_LEASE_REPLICA_WAIT_SECONDS` (2 s) for a standby to replay past
it, then reads there. It falls back to the primary on lag, on missing rows or
on recovery conflicts.

**Once per lease** it loads the option's `function`/`kwargs`/`short_name`, the
resources' paths in the pair's array order, and the category map for mapped
datasets. A missing option or resource, or an unknown processor, is a **setup
error**: every feature becomes a failed task with a `setup:` message.

**Geometries are loaded per block**, as WKB, via `feat_map → features`. A
feature missing on the primary was deleted, and is dropped from the page.

### 5. Compute

**For each block, then for each resource:**

- **Rasterstats functions that have a batch version** open the raster once per
  block.
- **All others** are called once per feature.

An exception on one feature/resource leaves that position NULL and makes the
feature status -1. Results are built into result rows in memory: one scalar for
single-resource pairs, position-aligned arrays for grouped pairs, and an
all-NULL row for "nodata".

**Between features, the stop check can abandon the page:**

- **Out of time** (assignment + lease duration − 60 s): the page is given back
  **with the attempt counted**, and the pair's pace is raised so the next page
  is smaller.
- **The worker is stopping:** the page gets `EXTRACT_WORKER_DRAIN_SECONDS`
  (840 s) from when the stop is first noticed. After that it's given back
  **with the attempt refunded**.

Neither can interrupt a processor call already in progress.

### 6. Complete

One synchronous transaction (`complete_lease`):

1. **`recheck`:** share-lock the same state rows and require each to be
   available with the **same epoch**. If not, an invalidating change happened
   during compute: give the page back as **deferred**, refunded. Sync's publish
   will re-token it.
2. **Lock the lease row** and check:
    - **Token differs:** someone took it over. Write nothing (**stale**).
    - **Pair no longer current:** **stale**.
    - **Dataset or option inactive:** give it back as **parked**, refunded.
3. **Insert one task row per feature** (status 1 or -1, `pair_id`,
   `submit_time`/`start_time` = when leased) with
   `ON CONFLICT DO NOTHING RETURNING id, fm_id`. A conflict means a request
   already created that task; the request's task and results win. A conflict
   on a *different* array is a hash collision: the pair backs off 300 s and the
   lease is kept.
4. **COPY the result rows** into `extract_data`, only for task rows that were
   just inserted.
5. **Delete the lease**, `WHERE token = <ours>`.

If anything fails:

- **Connection error:** rerun the whole transaction up to 3 times. If the
  lease is gone on a retry, an earlier attempt committed (or sync cancelled
  it), and nothing more is written.
- **A value the database can't store** (SQLSTATE 22001, 22003, 22P02, 22021,
  or a client-side encoding error): redo it with one **savepoint** per
  feature. A feature that can't be stored becomes a -1 task with no results,
  and its neighbours still commit.

**After the commit,** the pair's pace becomes `0.7 × old + 0.3 × this page's`.
That sets the next page size.

Why a page can be given back, and whether it counts as an attempt:

| Reason | Attempt counted? | When it's due again |
|---|---|---|
| Worker stopping, drain time ran out | No | Immediately |
| Computation hit the lease deadline | Yes | Immediately, with a smaller page |
| Epoch changed, or a guard was unavailable | No | Immediately, once its inputs are available |
| Dataset or option inactive at completion | No | When it's active again (parked) |
| Database failure | No, if the return succeeds | Slot backs off; expiry recovers a failed return |
| Unexpected load/compute exception | Yes | `min(300, 15 × 2^(attempts−1))` s, ±25% |
| Hash collision at completion | No | 300 s, and the pair backs off too |

### 7. Afterwards

- **A successful feature:** a status 1 task row plus its result rows. Nothing
  touches it again unless an input change resets it.
- **A failed feature:** a status -1 row. The error sweep returns it to pending
  while it has attempts left, and a later task-row claim retries it.
- **The pair:** its cursor has moved on. When it reaches the cap, the pair
  drops out of the candidates until a publish lowers the cursor.

---

## Example: a new boundary collection is ingested

While processing workers are running:

1. **The ingest transaction inserts** the `feature_collections` row, the
   `features` and the `feat_map` rows, say fm_ids 1,400,001–1,410,000.
    - The collection trigger **creates a clean state row** for the
      collection.
    - The `feat_map` trigger **marks the collection**: generation +1,
      `rewind_from = 1,400,000`. The epoch doesn't change, because this is
      additive.
    - All of it commits together.
2. **`BaseIngestCommand` calls `wake_sync()`**, and one Celery message is sent
   after the commit.
3. **Workers already scanning are unaffected.** The epoch didn't change, so
   their completions still pass `recheck`. Every current pair's cursor is below
   1,400,001 (the old cap was 1,400,000), and the cap has now moved up. New
   scans can pass into the new collection immediately, because a collection
   with only additive changes pending isn't a barrier.
4. **Sync** locks the collection's state row. With no items or coverage reset,
   it goes straight to **publish**: lock every watermark and current pair, then
   lower any above 1,400,000. Usually that's none, but it catches pairs whose
   ids moved past a gap before these rows committed. Then mark the collection
   clean.
5. **For each pair, the next lease claim** scans windows into 1,400,001+,
   finds no task rows there, and leases pages of up to 256 features. For each
   non-global dataset, coverage chunks first move the watermark across the new
   ids.
6. **Each completion** inserts the tasks and results and deletes its lease.
   When every pair's cursor reaches the new cap, the collection is fully
   processed.

**A shape edit to one of those boundaries goes differently.** In the same
transaction as the edit, its coverage is deleted, its collection's epoch is
bumped, the feature is logged as an item, and a rewind is recorded. Leases
holding that feature then fail `recheck` and are deferred. Sync deletes that
feature's tasks and results. Publish lowers every cursor and watermark below
the feature and re-tokens the leases that hold it. A lease then recomputes it
from the new shape.
