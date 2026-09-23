# Database

PostgreSQL 17 + PostGIS, run by CloudNativePG, reached through pgBouncer in
transaction pooling mode. Use `django.contrib.gis` for spatial fields.

This document records the decisions that govern how we query, index, and tune
this database, and why each was made. Most exist because of a production
incident or a measurement; those are cited inline so a future change can be
argued against evidence rather than taste.

The scale that motivates all of it: `extract_tasks` is heading for ~1.2 billion
rows across 56 partitions, processed at ~43,000 rows/minute.

---

## 0. Working rules

The short version. Each rule links to the section that justifies it.

**Writing a query against `extract_tasks` / `extract_data`**

- Always filter on `dataset_id`, including through joins and relation
  traversals. Group by dataset and issue one query per dataset if you must (§1).
- `EXPLAIN (ANALYZE, BUFFERS)` it. Many per-partition `Index Scan` nodes or a
  `Merge Append` means it is not pruning (§1, Appendix C).
- Never issue queries in a loop over tasks or features. Prefetch by chunk and
  look up from a dict — the cost is round trips, not query time (§7).

**Adding or changing an index**

- Check what it does to HOT updates. Any index mentioning a frequently-updated
  column — as a column *or* in a partial predicate — makes every update to it
  rewrite all indexes on the table (§3).
- Prefer partial indexes whose covered set *shrinks* over time to ones that grow
  with the table. Ask what the index costs when the table is at its final size,
  not today's (§3).

**Adding a background task**

- New task modules must be star-imported in `analytics/tasks/__init__.py`, or
  autodiscovery misses them and every worker drops the message with a `KeyError`.
  Verify with `celery -A geoquery inspect registered` (§8).
- If it writes results, confirm nothing depends on them; if it is a chord member,
  it must keep them (§9).
- One message in, one message out for self-chaining tasks — anything else grows
  the queue without bound (§2).

**Adding state that means "something is working on this"**

- Write the reaper at the same time. Every such marker we have added stranded
  work until one existed (§8).
- Self-expiring state still needs something to *trigger* a retry. Expiry alone
  only makes work claimable, not claimed (§8).
- Prefer a state that monitoring already treats as abnormal, or add an explicit
  check. A marker that looks like a normal transient state hides indefinitely (§8).
- If the work can outlive the staleness threshold, heartbeat it — otherwise the
  threshold is a duration limit, not a liveness check (§4).

**Anything that runs inside a transaction**

- Keep file I/O, HTTP calls, and long computation out of transactions that hold
  row locks (§4).
- `SET LOCAL`, never `SET` — session settings leak across pooled transactions
  (§5).
- Long transactions consume pool capacity out of all proportion to their
  connection count (§5).

**Changing database settings**

- Check the pool budget against `max_connections` before raising any pool (§5).
- Establish a baseline, change one variable, measure over hours (§6, Appendix C).
- Runtime-reloadable parameters can be patched on the `Cluster` for experiments;
  declare anything permanent in the chart, and declare storage size in the
  environment overlay explicitly (§10).

**Before concluding anything from a measurement**

- Confirm what is actually waiting before optimising. Twice now the obvious
  culprit was not the bottleneck (§5, §6).
- Watch for sampling aliasing and post-rollout transients (Appendix C).

---

## 1. Partitioned tables: every query must name `dataset_id`

`extract_tasks` and `extract_data` are `PARTITION BY LIST (dataset_id)` with
`PRIMARY KEY (dataset_id, id)`.

**Rule: every query touching them must filter on `dataset_id`.**

`id` is the *second* PK column, so a filter on `id` alone cannot seek the index.
Postgres probes all 56 partitions instead of one. Measured on production: a
single-row claim took **4.1 s unpruned versus 0.2 ms pruned**.

This applies to relation traversals too, not just direct manager calls. A
`FeatureCollection.objects.filter(featmap__extracttask__requestmap__request=…)`
joins *into* a partitioned table without `dataset_id` and is just as slow — that
form survived an audit that only grepped for `.objects.` on the partitioned
models.

Because the partition key is rarely known up front, the working pattern is to
group by dataset first and issue one query per dataset. `merge._group_by_dataset`
exists for exactly this.

Four production hangs (`0.43.1`–`0.43.4`) were all this single mistake in
different call sites.

**Exception, and it is load-bearing:** the task claim (§2) *cannot* prune,
because it asks for the globally highest-priority pending task and does not know
which dataset will win. That is the one query allowed to fan out, and §2 is about
paying for it.

---

## 2. Task claiming: serialized on purpose, amortized by batching

`claim_pending_tasks` takes `pg_advisory_xact_lock(CLAIM_LOCK_ID)` so claims run
one at a time fleet-wide.

**Why serialize deliberately:** with 150+ worker slots self-chaining, concurrent
`FOR UPDATE SKIP LOCKED` transactions all raced over the same leading index rows.
Each had to step past every row the others had locked, so the work to find an
open row grew with the *number of claimers*, not the backlog. Queueing is
cheaper than fighting.

**The claim is inherently expensive.** It merge-appends 56 partition indexes to
return a handful of rows: **~125 ms, ~33,000 buffer hits**. Combined with the
lock, that caps the whole fleet at roughly **8–15 claims/second** regardless of
worker count.

So `throughput ≈ claims/sec × batch size`, which is why batching is the lever:

| Batch | Tasks/min | Limiting factor |
|---|---|---|
| 1 | ~975 | claim |
| 4 | ~4,100 | claim |
| 16 | ~18,800 | claim |
| **64** | **~43,000** | **extraction work (~0.45 s/task)** |

At 64 the claim stopped being the bottleneck: connections parked on the advisory
lock fell from ~30 to 0–3, and `pooler-rw` went from fully saturated to having
headroom. Scaling turned sublinear at that point, which is the *signal* that the
limit moved rather than a disappointment.

Tunable via `EXTRACT_TASK_CLAIM_BATCH`. Raising it costs blast radius: a worker
dying mid-batch strands that many tasks until `free_stale_processing_tasks`
reaps them.

**`_MAX_CLAIM_ROWS = 1024`** caps a single claim regardless of the limit asked
for. The beat's cold-start top-up requests `idle_slots × batch_size` — at 384
slots and batch 64 that is 24,576 tasks, which builds **49,152 bind parameters
against PostgreSQL's 65,535 ceiling**, and holds the fleet-wide lock while
merge-appending tens of thousands of rows in priority order.

**One message in, one message out.** `run_extract_task` self-chains, so
dispatching more than one successor per message consumed makes the queue grow
without bound. The batching happens *inside* the message.

---

## 3. Indexes on `extract_tasks`: the partial claim index stays

Five indexes per partition; **index bytes (36 GB) exceed heap bytes (32 GB)**.
The important one:

```sql
CREATE INDEX … ON extract_tasks_ds_N (priority DESC, submit_time, id)
  WHERE (status = 0)
```

**Decision: keep the `WHERE status = 0` predicate, accepting that it makes HOT
updates impossible.**

`status` appearing in the predicate means Postgres treats it as indexed, so every
status transition changes index membership and disqualifies the update from HOT.
Result: `n_tup_hot_upd` is ~0 against tens of millions of updates, and each of
the two status transitions per task rewrites all five index entries.

We measured the alternative properly (Appendix A). Getting HOT requires **both**
removing `status` from the index **and** lowering `fillfactor` — neither alone
does anything — and at `fillfactor=50` you get 97.8% HOT.

**Why we still keep the predicate:**

- The partial index only covers *pending* rows, so it **shrinks as work
  completes**. Drop the predicate and it grows monotonically toward 1.2B entries
  and is scanned while filtering for the `status = 0` rows that, at steady state,
  become rare. The cost lands exactly when the table is largest.
- **HOT's benefit decays; the index cost is permanent.** Each task is updated
  exactly twice in its life, so the WAL saving is proportional to the *build-out
  rate* and largely evaporates at steady state. The scan cost is proportional to
  *table size*, which is forever.
- The claim is already the fleet's throughput ceiling (§2). Reintroducing a
  degrading scan there is the last place to spend.

No index involving `status` — predicate or column — permits HOT on status
changes. There is no clever index that gets both.

---

## 4. Request sweep: claim → work → finalize

`_manage_user_requests` once wrapped each request's whole cycle in one
`transaction.atomic()`, holding that row's lock across minutes of file I/O. Since
the sweep selects rows and immediately updates them, every concurrent sweep
queued behind it in FIFO order: **33 backends stacked, the oldest blocked 2 h
45 m**.

The cycle is now three scopes:

1. **Claim** — `select_for_update(skip_locked=True)` filtered on
   `status__in=(-1, 0)`, sets `status=2`, **commits**.
2. **Work** — task checks and output build, outside any transaction.
3. **Finalize** — one short transaction for the terminal status.

`status=2` always meant "a sweep has this" and the selection query always skipped
it, but it was written *inside* the long transaction, so it stayed invisible for
exactly as long as it mattered. Committing the claim is what makes it real;
`skip_locked` is what makes a contended request skip rather than queue.

**Terminal writes are fenced** on `filter(id=…, status=2, process_time=claim_time)`
so a sweep that lost its claim to the reaper cannot mark a request complete or
email a link while another sweep rebuilds it.

**A committed claim needs a heartbeat.** `_ClaimHeartbeat` refreshes
`process_time` on an interval, each refresh fenced on the claim it extends.
Without it the stale threshold is a *build duration limit* rather than a liveness
check: with hourly reaper ticks and a 30-minute threshold, any build over ~90
minutes was reaped on every attempt and could never complete — silently, because
it returns to `status=0`, which is not an error state. Hour-long builds are
normal here, so this is not an edge case. A failed heartbeat also tells the sweep
it lost the claim, so it stops early instead of building output nobody will use.

**Output builds are atomic.** `_build_output` writes into
`.{request_id}.building.{uuid4}` and renames it into place, because two sweeps
can legitimately be building the same request once a reaper can reset a live
claim. Displaced output moves to `.{request_id}.replaced.{uuid4}` rather than
being deleted, so a failed swap can restore it.

---

## 5. Connection pooling: transaction-scoped, and budgeted

Three pgBouncer pools in **transaction pooling** mode: `api` (backend only),
`ro` (backend reads), `rw` (everything else). A server slot is held for the
duration of a *transaction*, so long transactions consume far more pool capacity
than their connection count suggests — six builder workers running 11–20 s
`INSERT`s could halve throughput for everyone else.

**`SET LOCAL`, never `SET`.** A session-level `SET` persists on the pooled server
connection and leaks into whatever transaction reuses it next. Setting
`synchronous_commit = off` that way would silently make unrelated writes
non-durable. Django's `CONN_MAX_AGE = 0` and `DISABLE_SERVER_SIDE_CURSORS = True`
are for the same reason — server-side cursors are connection-local and break
under transaction pooling.

**The pool budget must stay under `max_connections`.** `default_pool_size ×
instances`, summed across all three pools, is the real ceiling. It currently sums
to exactly `max_connections = 100` with no headroom; a past incident had a
migration Job unable to get a connection because the poolers had taken them all.
Raise `max_connections` before raising any pool.

Note that pool saturation is not always a capacity problem. Before §2's batching,
~30 of ~40 connections were workers *blocked on the advisory lock doing no work*.
Removing the claim storm freed them without changing a single pool setting.

---

## 6. Write path: bandwidth-bound, not lock-bound

Backends queue on the `WALWrite` LWLock; `effective` IO wait and row-lock waits
are near zero by comparison. WAL runs **~2.8 KB/task** (builder idle) to
**~3.9 KB/task** (builder running), against a ~200-byte row — the amplification
is §3's non-HOT updates rewriting five index entries twice per task, plus
`full_page_writes`.

**`commit_delay` was tested and rejected** (Appendix B). At 600 µs it did reduce
waiters 21.8 → 13.4 — group commit worked — but throughput fell 17%, monotonically
worse as the delay grew. *Fewer waiters and less throughput* is the signature of a
**bandwidth** limit rather than a lock limit: batching commits shortens the queue
without adding write capacity. Left at 0.

**Build batches commit asynchronously — mechanism confirmed, benefit unproven,
retained under observation.** `_run_batch` issues
`SET LOCAL synchronous_commit = off`, taking the largest single write contributor
out of the fsync path entirely. That part is verified directly: `WALWrite` waiters
are now `extract_data` inserts and `UPDATE extract_tasks`, with zero from builder
INSERTs.

It has **not** been shown to improve throughput (Appendix B). Retained rather
than reverted on the theory that it may matter under heavier builder load than
two workers produce — to be re-measured over days, and specifically whenever
`N_EXTRACT_TASK_BUILDERS` is raised. It buys a real durability trade for no
measured gain, so this is a live question, not a settled one.

**That trigger has fired.** `N_EXTRACT_TASK_BUILDERS` went 2 → 4 on 2026-09-23,
once a 12-hour window showed processing clearing tasks 2.5× faster than the
builder created them (905,709/hr built against 2,276,650/hr completed). The
re-measurement described in Appendix B is now due, and it is the same run that
answers whether the raise itself paid off — control for builder output per hour
and discard hours containing the rollout.

Safe because the work is regenerable: an unclean crash loses at most ~200 ms of
speculative `extract_tasks` rows whose `completed_up_to_fm_id` will not have
advanced, so the next pass rebuilds exactly what was lost. Revertible via
`EXTRACT_TASK_BUILD_SYNCHRONOUS_COMMIT=1`, no deploy needed.

**Do not extend async commit to the processing path** — a lost `status=1` means
re-running real extraction work. The pattern does not generalise either: under
transaction pooling, `SET` rather than `SET LOCAL` leaks non-durability into
unrelated transactions (§5).

---

## 7. Round trips, not query time

The merge step once took **3 h 38 m** for a 1,040-task request. The queries were
not slow: a single one measured **0.111 ms** with a correct partition-pruned index
scan, and the total database work was under a second. The cost was **~5,200
sequential round trips**, each waiting ~2.5 s for a pooler slot held by the claim
storm.

`merge_task_results` ran five queries *per task*; `merge_task_features` ran three
*per feature*. Both now prefetch per chunk and look up from dicts, so query count
is a function of chunks and datasets rather than task count. The same 2,890-task
build now takes **2.3 seconds**.

**Rule: when a loop issues queries, batch it by chunk** — and keep `dataset_id` on
every batched query (§1). Chunk (`MERGE_CHUNK_SIZE = 1000`) rather than
prefetching everything, because 61k-task requests exist.

---

## 8. Every claim marker needs a reaper

Any state meaning "something is working on this" strands work if the worker dies.
We have found this four times; the recovery table is now:

| State | Meaning | Recovery |
|---|---|---|
| `extract_tasks.status` 2 / 3 | claimed / queued | `free_stale_processing_tasks` |
| `requests.status = 2` | sweep working | `reset_stale_requests` |
| `requests.status = 4` | awaiting materialization | `_redispatch_unmaterialized_requests` |
| `.building.*` dirs | crashed build | collected by `reset_stale_requests` |
| `.replaced.*` dirs | displaced output | **restored** if `request_dir` missing, else deleted |
| `extract_task_build_progress.claimed_at` | pair being built | self-expires (`CLAIM_STALE_MINUTES`) |
| `extract_task_build_run.in_progress` | wave running | self-expires (`RUN_STALE_MINUTES`) |

Two lessons worth keeping:

- **Self-expiring state still needs a trigger.** The builder's markers expire
  correctly, but nothing re-dispatched workers to act on them, so a wave killed
  by a deploy cost up to a full day. The beat is now hourly, guarded by
  `try_acquire_build_run` so it tops up rather than stampedes.
- **`status = 4` was invisible.** It is a normal transient state and `-2` is the
  only status monitoring reads as an error, so a request stranded there looks
  identical to one submitted a second ago. One sat for four days with all its work
  long finished. `.replaced.*` has the same property: it may be the *only* copy of
  a completed request's output, so it must be restored, never blind-deleted.

---

## 9. Celery result backend

`CELERY_RESULT_BACKEND = "django-db"`.

**Do not set `CELERY_TASK_IGNORE_RESULT` globally.** `sweep_coverage_records`
uses a `chord`, and a chord is the one canvas primitive that genuinely needs the
result backend — it counts header completions to decide when to fire its body.
Turning results off globally leaves coverage sweeps hanging silently, never
dispatching `build_extract_tasks`. A test pins this so the global setting fails
loudly rather than in production.

`run_extract_task` opts out individually (`ignore_result=True`). It was ~100% of
the table — result rows tracked task messages 1:1 — and nothing reads them.

`celery.backend_cleanup` **must be scheduled explicitly**; it is not automatic.
Without it and `CELERY_RESULT_EXPIRES`, the table grew to 2.8M rows / 4.4 GB in
43 hours with no bound.

---

## 10. Cluster settings and storage

Parameters live in the Helm chart at `database.postgresql.parameters`, rendered
into the CNPG `Cluster`. Runtime-reloadable ones (e.g. `commit_delay`) can be
patched on the `Cluster` for experiments — Flux has drift detection disabled, so
a patch persists until the next chart upgrade.

**Declare storage size explicitly in the environment overlay.** The prod overlay
once overrode only `storageClass`, inheriting the chart default of 50 Gi while the
live PVCs had drifted to 150 Gi. Nothing was broken — CNPG expands but never
shrinks — but the *spec* is what a **new** instance gets, so a replaced replica
would have been provisioned at 50 Gi and could not have held the database. That
fails during a failover, i.e. the worst moment. Both halves matter: existing
volumes expand, and future instances are created at the right size.

Expansion is online with `ceph-block` (`allowVolumeExpansion: true`) — no restart,
no failover.

---

## Appendix A — HOT update experiment

Controlled 2×2, 20,000 rows each, running the real `status 0 → 3` transition:

| fillfactor | `status` in index | HOT % |
|---|---|---|
| 100 | yes (predicate) | 0.0% |
| 85 | yes (predicate) | 0.0% |
| 100 | no | 0.0% |
| 85 | no | 18.3% |

Both conditions are necessary; neither alone achieves anything.

Fillfactor sensitivity (no `status` in index, both transitions with a vacuum
between):

| fillfactor | HOT % | heap size |
|---|---|---|
| 85 | 18.3% | — |
| 70 | 55.5% | 3,008 kB |
| **50** | **97.8%** | **2,496 kB** |
| 30 | 100% | 4,000 kB |

`fillfactor=50` is the optimum — note it produces a *smaller* heap than 30,
because under-filled pages cost more than the bloat they prevent.

Conclusion: mechanism confirmed, change **not** adopted (§3).

## Appendix B — write-path experiments

Two attempts to buy write headroom. Both are recorded because the *negative*
results are what establish that the limit is storage bandwidth.

**B1 — `commit_delay`.** Five to six one-minute samples per arm, builder running
in all:

| `commit_delay` | Tasks/min | `WALWrite` waiters |
|---|---|---|
| 0 (baseline) | **41,605** | 21.8 |
| 100 µs | 37,994 | 22.3 |
| 600 µs | 34,583 | **13.4** |

Group commit worked — waiters fell — but throughput fell further, monotonically
with the delay. Reverted to 0 (§6).

**B2 — builder `synchronous_commit = off`.** Hourly aggregates either side of the
rollout, since minute-scale variance (29k–52k) swamps the effect size:

| Arm | Hours | Mean tasks/min | sd |
|---|---|---|---|
| Synchronous | 4 | 35,517 | 4,322 |
| Asynchronous | 3 | 38,828 | 3,037 |

Async is ~9% higher, but the gap is smaller than either standard deviation, and
one *sync* hour (40,543) beat an async hour. Builder output was unchanged
(~800k rows/hour both ways) — the workload whose commits left the fsync path did
not itself speed up, which is the strongest argument that the effect is not real.
**Retained under observation, not adopted on evidence** (§6).

Method note for the re-test: hourly throughput is reconstructible retrospectively
from `extract_tasks.update_time`, so no instrumentation is needed — but control
for builder output per hour, and discard hours containing a rollout.

## Appendix C — measurement recipes

```sql
-- what is actually waiting, and on what
SELECT wait_event_type, wait_event, count(*) FROM pg_stat_activity
WHERE datname='app' AND state<>'idle' GROUP BY 1,2 ORDER BY 3 DESC;

-- pool saturation (compare against default_pool_size per instance)
SELECT client_addr, count(*), count(*) FILTER (WHERE state='active')
FROM pg_stat_activity WHERE datname='app' GROUP BY 1 ORDER BY 2 DESC;

-- HOT ratio: n_tup_hot_upd near zero means every update rewrites all indexes
SELECT relname, n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables
WHERE relname LIKE 'extract_tasks%';

-- unpruned partition scans show as many per-partition Index Scan nodes
EXPLAIN (ANALYZE, BUFFERS) <query>;
```

WAL rate over a window (the headline write-load number):

```sql
SELECT pg_current_wal_lsn() - '0/0'::pg_lsn;  -- sample twice, diff, / seconds
```

**Beware sampling artifacts.** Builder inserts land 5,000 rows per batch sharing
one `NOW()`, so per-minute counts of `submit_time` alias badly — bucket at 5
minutes or longer. And every rollout injects a recovery transient: minute-scale
throughput varies 29k–52k, which swamps most effect sizes. Compare hours, not
minutes.
