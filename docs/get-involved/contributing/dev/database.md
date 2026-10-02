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

**Computing global datasets**

- Prefer block extraction to the per-task path for bulk work: one claim and
  one commit per block of thousands of tasks, rather than several per task
  (§11).
- Write task rows directly in their final state. A row that never sits at
  `status = 0` never enters the claim index (§3, §11).

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
the three status transitions per task (0 → 3 at dispatch, 3 → 2 at claim,
2 → 1 at finalize) rewrites all five index entries. Block extraction (§11)
writes its rows once, already complete, so it pays none of them.

We measured the alternative properly (Appendix A). Getting HOT requires **both**
removing `status` from the index **and** lowering `fillfactor` — neither alone
does anything — and at `fillfactor=50` you get 97.8% HOT.

**Why we still keep the predicate:**

- The partial index only covers *pending* rows, so it **shrinks as work
  completes**. Drop the predicate and it grows monotonically toward 1.2B entries
  and is scanned while filtering for the `status = 0` rows that, at steady state,
  become rare. The cost lands exactly when the table is largest.
- **HOT's benefit decays; the index cost is permanent.** Each task is updated
  exactly three times in its life, so the WAL saving is proportional to the *build-out
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

**Non-Django clients need the same care.** The MCP server's OAuth proxy keeps
its state in `mcp_oauth_state` through asyncpg, not Django, and reaches it via
`pooler-tasks`. asyncpg's default statement cache names prepared statements on
a server connection the next transaction may not get, and its default pool
holds ten idle connections per process, so `mcp_server.auth` builds the pool
with `statement_cache_size=0` and `max_size=MCP_STATE_POOL_SIZE`. The proxy's
store never deletes expired rows; `purge_expired_oauth_state` does, hourly.

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
| `extract_task_build_progress.block_claim_token` | block being computed | self-expires (`EXTRACT_BLOCK_LEASE_MINUTES`), re-dispatched by `dispatch_block_chains` |

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

**Prod must override `max_wal_size` to 16GB / `min_wal_size` to 4GB.** The chart
defaults to 8GB/4GB; prod sets 16GB/4GB in its environment overlay. This is not
cosmetic tuning — at the old 4GB ceiling, 899 of 1002 checkpoints over 120h were
forced by WAL volume (89.7%), emitting 601.6M full-page images across 2,530 GB of
WAL and 95h of checkpointer write time, out of 120h of wall clock.

The mechanism: a checkpoint *requested* by hitting `max_wal_size` ignores
`checkpoint_completion_target` and writes as fast as it can. Afterward, the first
touch of every page emits a full-page image, which refills WAL and triggers the
next one sooner. The loop is self-reinforcing, and it throttles ordinary
processing, not just bulk operations — raising the ceiling to 16GB took
steady-state throughput from 1.42M to 4.5M tasks/hr and made a 136.8M-row
`extract_tasks` reset run 2.06× faster (12 forced checkpoints instead of 899).

It bites hardest on bulk `UPDATE`s of `extract_tasks` because HOT never applies:
`status` appears in the `WHERE status = 0` predicate of the partial claim index
(section 3), which disqualifies the heap-only path for every row, so each row
churns all five of a partition's large indexes. On the `ds_23` partition,
`n_tup_hot_upd` was **0** out of 879.7M updates. See also Appendix A.

Both parameters are `sighup` context, so this is a config **reload** — CNPG applies
it without a restart or failover (`pending_restart` stays false).

**Size any increase against `ceph df`, not `df`.** The data volume is thin
provisioned, so filesystem free space overstates what is actually available. Each
of the three instances retains its own `pg_wal` on its own PVC, so a WAL delta
costs three times that in pool space, and prod shares `ceph-blockpool` with
staging. That three-times multiplier is why the chart default stays at 8GB rather
than matching prod.

---

## 11. Block extraction: one claim and one commit per block

The per-task path pays per task for everything in §2–§6: a builder INSERT,
three non-HOT status updates, a share of the serialized claim, and three
commits. It also re-reads the raster for every task: `rasterstats` opened the
file and read the feature's window once per processing option, so min, max,
mean, sum and count of the same pixels were five reads. At ~700 tasks/s the
workers were queueing on the database with CPU to spare, and no setting
removes a cost that is paid per task.

`analytics/blocks.py` computes global datasets in **blocks** instead: one
`resource_ids` unit × up to `EXTRACT_BLOCK_SIZE` feat_map rows × every active
processing option of that resource.

- **Claim.** Lease the resource's `extract_task_build_progress` pairs (all
  options at the same `computed_up_to_fm_id`) and take the next range of
  feat_map ids above that watermark. Claims are serialized on
  `pg_advisory_xact_lock(BLOCK_CLAIM_LOCK_ID)`: the claim is two statements
  (lock a seed pair, then its siblings), and with `SKIP LOCKED` alone a second
  claimer arriving between them skipped the locked seed and leased the same
  resource's next option by itself, splitting the resource into two blocks
  that each read the raster. Unlike §2 the lock costs nothing that matters:
  the table holds thousands of rows, not billions, so it is held for a few
  millisecond statements once per block. `SKIP LOCKED` stays for the rows'
  other writers (the builder's batch, a block's fence), which the claim steps
  past rather than waits on.
- **Scan.** One partition-pruned query finds which of the range's tasks are
  already done (1) or in flight on the per-task path (2, 3). Those are
  skipped, so the ~700M tasks the per-task path already completed cost one
  index range scan per block.
- **Compute.** One `rasterstats` call per resource and option group over every
  geometry: one raster open, one windowed read per feature for all stats.
  Percentage coverage weighting or selection uses separate batches for
  Point/MultiPoint and other geometries, then restores input order. The
  installed rasterstats disables coverage flags when it encounters a point
  and otherwise carries that state into subsequent polygons: a mixed batch
  reproduced a polygon sum of 567 instead of 425.8800048828125. Isolating
  points preserves the per-task values while retaining batching within each
  group. Parity is tested per stat, categorical, nodata, grouped resources,
  and mixed geometries with coverage weighting/selection and geometry
  splitting (`limit`) in `test_blocks.py`. A batched call that raises
  is retried per feature, so a bad geometry fails only its own tasks -- but
  only once the resource is shown to be readable. A resource's first failure
  opens the file itself; if that fails the block errors and backs off (below)
  with nothing written, instead of recording an outage as a -1 for every task
  in the range. The share of failed features cannot make that distinction,
  because a block that recomputes only -1 rows fails all of them legitimately.
- **Write.** One transaction: a `COPY` into transaction-scoped temp tables,
  the `extract_tasks` rows written directly at `status = 1` (or -1 with an
  error), their `extract_data`, and last the fenced watermark update.

**Rows are written once, already complete.** They never sit at `status = 0`,
so they never enter or leave the claim index, and none of §3's index
rewrites happen. `complete_time` is set because the stats completion chart
counts only rows that have one.

**Coexisting with the per-task path.** The write takes over existing rows in
place with an `UPDATE`, only at 0 (built, unclaimed) or -1 (failed), and then
inserts the rest. A row the per-task path claims after the scan (2 or 3)
fails the `UPDATE`'s `WHERE`, keeps its own result, and is counted
`unavailable`. Both sides lock with `SKIP LOCKED`, so neither waits on rows
the other holds; a row a block skips stays with the per-task path. It is an
`UPDATE` and not an upsert because `INSERT ... ON CONFLICT DO UPDATE` draws an
id from `extract_tasks`' 32-bit identity for every row it takes over. Values
pass through the `ExtractData` model fields before the `COPY`, so an array
whose positions disagree on type is stored as `bulk_create` stores it, and a
value its column cannot take -- one the field cannot coerce, an integer
outside PostgreSQL bigint bounds, or one too long for `varchar(100)` -- fails
only its own task, as on the per-task path, rather than the whole block.
Bigint bounds are checked after coercion for both scalar and array columns;
Django's field preparation alone does not enforce them. Conversion
`OverflowError` (for example, an infinity coerced into an integer array) is
also caught per task. Without these checks, one invalid value aborts the
block before its watermark advances and repeats at every lease expiry.
Regression tests verify both bigint endpoints, out-of-range values,
conversion overflow, preservation of prior results, and progress into later
blocks. Tasks a block marks -1
are reset by `manage_processing_task_errors` and retried by the per-task path:
blocks have no retry machinery of their own. User requests and non-global
datasets stay on the per-task path.

**The lease is fenced, heartbeated and re-triggered** (§8). Every write is
fenced on `block_claim_token`, so a worker whose lease was taken over rolls
back everything it computed. The fence runs last in the write transaction,
which locks `extract_tasks` rows before the progress row -- the same order as
the builder's batch. Run first, the two deadlocked when they reached the same
pair: the block waited on a row the builder had inserted, and the builder
waited on the progress row the block's fence held. A heartbeat thread
refreshes the lease at a fifth of `EXTRACT_BLOCK_LEASE_MINUTES` so a slow
block is not mistaken for a dead one (§4); a beat that fails closes its
connection, so the next one reconnects instead of failing on a dropped
connection until the lease expires. The lease is refreshed once more
immediately before the write, which therefore always starts with a full
lease period. `run_extract_block` self-chains one
message in, one out (§2), and ends the chain when there is nothing to claim
or the claim itself raised. A block that raises after its claim keeps its
lease for another full period instead of releasing it, and the chain moves
on: released, a deterministic failure was the lowest claimable block, so it
took down every chain that claimed it in turn. `geoquery_extract_blocks`
counts blocks by outcome, so one failing repeatedly shows as a steady `error`
rate. `dispatch_block_chains` refills idle `blocks`-queue slots every five
minutes, which is also what claims an expired lease.

**One commit per block.** At block size 2,000 and five options that is one
commit per 10,000 tasks, against three per task before. That is the change
that matters for §6: whether the write limit there is bandwidth or per-commit
flush latency, the per-task path paid it ~2,000 times a second at 700
tasks/s.

**The builder is optional once blocks run.** Blocks never read the pending
backlog the builder creates; they take its rows over when they reach them.
`EXTRACT_TASK_BUILDER_GLOBAL_ENABLED=0` stops the global build from every
entry point -- the scheduled wave, the management command,
`trigger_coverage_and_extract`'s inline fallback, and worker messages already
queued when the flag changes -- and leaves the non-global branch running. The
builder's insert has `ON CONFLICT DO NOTHING`
so that a block committing the same rows mid-statement cannot fail its
5,000-row batch.

**Not yet measured in production.** Check parity and per-core rates on real
data with `manage.py benchmark_extract_block --resource <id> [--write]`
before enabling, then compare whole hours as in Appendix B. Roll out with
`EXTRACT_BLOCK_DATASETS` before enabling everywhere.

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
