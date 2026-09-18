# Sweep Transaction Scope — Design

## Problem

`_manage_user_requests` (`analytics/management/commands/manage_user_requests.py`)
wraps each request's entire processing cycle in a single
`transaction.atomic()` block:

1. validate `request.data`
2. read `original_status`, set `prepare_time` if it was `-1`
3. set `status=2` + `process_time`
4. `_check_request_tasks` — DB reads plus a priority-bump UPDATE
5. `_build_output` — **file I/O**: merge every task result into a DataFrame,
   write CSV, render documentation HTML, dump JSON, copy a PDF, write a
   GeoPackage, build a zip, then `chmod` the whole tree
6. set `status=1` + `complete_time`

Postgres holds a row lock on that `requests` row for the entire block. Any
slowness anywhere inside — a slow query, a large merge, slow disk, a big zip
— extends that lock. Because the sweep's own selection query reads
`status=-1`/`status=0` rows and then immediately `UPDATE`s them, every
*other* concurrently-running sweep blocks on that same row lock and queues
behind it in strict FIFO order.

This produced three separate production incidents on 2026-09-17, each with
the same signature: one slow query at the head of a chain, and 20-33
`_manage_user_requests` backends stacked behind it, the oldest blocked for
over 2h45m. Each incident was resolved by fixing the specific slow query
(four partition-pruning fixes, `0.43.1` through `0.43.4`), but the
amplifier was never addressed: *any* future slowness inside that block
reproduces the pileup.

The amplification also got worse on 2026-09-17, when request dispatch moved
to a `post_save` signal — sweeps now fire on every materialization
completion in addition to the 5-minute beat, so more sweeps run
concurrently and collide more often.

### The claim marker that cannot claim

`status=2` already exists and already means "a sweep is working on this" --
it is set at step 3 above, and the sweep's selection query deliberately
matches only `-1` and `0`, never `2`. The intent is clearly that a claimed
request should be skipped by other sweeps.

It cannot work, because it is written *inside* the transaction and only
becomes visible when that transaction commits -- which is after all the
work is already done. Until then, every other sweep sees the row's
pre-transaction status (`-1`/`0`), tries to claim it, and blocks on the row
lock instead of skipping it.

This is the whole bug: the claim exists but is invisible for exactly as long
as it matters.

## Design

Split the single long transaction into **claim → work → finalize**, so locks
are held only for the two short status transitions and never across file I/O.

### Phase 1 — claim (short transaction)

```python
with transaction.atomic():
    row = (
        Request.objects
        .select_for_update(skip_locked=True)
        .filter(id=request_id, status__in=(-1, 0))
        .values("id", "status")
        .first()
    )
    if row is None:
        continue  # another sweep holds it, or its status moved on
    original_status = row["status"]
    updates = {"status": 2, "process_time": timezone.now()}
    if original_status == -1:
        updates["prepare_time"] = timezone.now()
    Request.objects.filter(id=request_id).update(**updates)
```

`skip_locked=True` is what removes the pileup: a request another sweep is
mid-claim on is skipped outright rather than queued on. The `status__in=(-1, 0)`
re-check inside the lock matters because `request_objects` is built as a list
up front, so a row's status may have changed between selection and claim.

Once this commits, `status=2` is visible to every other sweep, and the
existing selection query already excludes it. The claim finally functions.

### Phase 2 — work (no transaction, no locks held)

`_check_request_tasks` and `_build_output` run outside any transaction.
`_check_request_tasks`'s priority-bump UPDATE runs in autocommit, which is
correct — it is an independent, idempotent nudge, not part of any invariant.

### Phase 3 — finalize (short transaction)

```python
with transaction.atomic():
    Request.objects.filter(id=request_id).update(
        status=1, complete_time=timezone.now()
    )      # or status=0 when missing_items > 0
```

### What is no longer atomic, and why that is correct

Today's single transaction implies "status transition and output build
succeed or fail together." That guarantee was never real: `_build_output`
writes files, which a database rollback cannot undo. A crash mid-build
already left a half-written `request_dir` behind while rolling the status
back. Splitting makes the actual behavior explicit instead of implied.

What still needs atomicity — and keeps it — is each individual status
transition, which is a single-row UPDATE.

## Crash recovery

Committing the claim introduces one genuinely new failure mode: if the
process dies between claim and finalize, the request is stranded at
`status=2`, which the sweep's selection query ignores. Today a crash rolls
the claim back and the request is retried naturally.

This is the same trade `ExtractTask` already makes, and it is resolved the
same way: a reaper.

**New:** `analytics/management/commands/reset_stale_requests.py`, sitting
alongside the existing `reset_errored_requests.py` and mirroring
`free_stale_processing_tasks.py`:

```sql
UPDATE requests
SET status = 0
WHERE status = 2
AND process_time < NOW() - INTERVAL 'N minutes'
```

with a `@shared_task` wrapper in `analytics/tasks/maintenance.py` and an
hourly `CELERY_BEAT_SCHEDULE` entry, exactly as
`free_stale_processing_tasks` has.

Threshold: the existing `STALE_TASK_MINUTES` setting (default 30), reused
rather than adding a second stale-threshold knob.

Reaped requests go to `status=0`, **not** `-1`. `-1` would re-trigger the
"request received" notification on the retry, since `send_received_email` is
driven by `original_status == -1`. `0` re-checks silently.

Retry is safe: `_build_output` begins with
`shutil.rmtree(request_dir, ignore_errors=True)`, so a retried build
overwrites any partial output rather than merging into it.

**Known risk:** a legitimately slow large build (61k-task requests exist in
production) could exceed 30 minutes and be reaped mid-flight, restarting
from scratch. Mitigated by the four partition-pruning fixes already shipped
(`0.43.1`-`0.43.4`), which removed the hours-long queries that made builds
slow in the first place, and by the idempotent retry above. If reaping is
observed in practice, the threshold is the knob to turn.

## dry_run

Today `dry_run` writes `status=2`, does the work, then reverts to
`original_status` at the end of the transaction. With split transactions
that write-then-revert is both unnecessary and more fragile (a crash leaves
the reverted-to status unwritten).

`dry_run` now skips the claim entirely — no `status` write at all — and runs
the same checks it does today. `_check_request_tasks` already takes
`dry_run` and skips its priority-bump UPDATE on that basis.

**Note on existing `dry_run` behavior, deliberately preserved:**
`_build_output` *is* called under `dry_run` today whenever
`missing_items == 0` — it is inside the `else` branch, which `dry_run` does
not guard. So a `dry_run` sweep currently writes a full `request_dir`
(CSV, HTML, JSON, PDF, GeoPackage, zip) to disk and only reverts the
*status* afterward. That is arguably wrong for a flag named `dry_run`, but
it is pre-existing behavior that nothing in this design depends on, and
changing it is a separate decision. This design changes only which status
writes happen under `dry_run` (none), leaving the file-writing behavior
exactly as it is.

## Notifications

Unchanged in placement: both `_notify_user` calls already happen after the
transaction, outside it, specifically so a notification failure cannot roll
back committed request state. They stay after phase 3.

The "received" notification remains driven by `original_status == -1`, which
is captured during the claim and carried through.

## Testing

- **Claim skips a request another sweep holds:** two connections
  (`TransactionTestCase`, since `TestCase`'s single wrapping transaction
  cannot express real concurrency — the existing `ClaimLockContentionTest`
  in `test_dispatch.py` establishes this pattern), one holding a claim, the
  second sweep must skip rather than block.
- **Claimed request is invisible to a second sweep:** a request at
  `status=2` is not picked up, asserted against the real selection query.
- **Locks are not held across `_build_output`:** assert via
  `pg_stat_activity` (or by observing that a concurrent claim on a
  *different* request succeeds while a build is in flight) that no `requests`
  row lock is held during the build phase.
- **Reaper resets a stale claim to 0, not -1:** a `status=2` request with an
  old `process_time` is reset to `0`; a fresh one is untouched.
- **Reaped-and-retried build overwrites partial output:** a request with a
  partially-written `request_dir` completes cleanly on retry.
- **`dry_run` writes no status:** status is unchanged before and after.
- **Existing end-to-end flow still reaches `status=1`** — `test_manage_user_requests.py`'s
  full submit → materialize → sweep → complete test must pass unmodified in
  intent.

## Out of scope

- **Reducing how often sweeps fire.** Per-request claiming makes concurrent
  sweeps safe (they skip claimed requests instead of queueing), which is the
  correctness fix. Extra sweeps still each scan the `-1`/`0` request set,
  which is wasteful but bounded and no longer dangerous. Debouncing the
  `post_save`-triggered dispatch is a separate optimization.
- **Further partition-pruning work.** The four fixes shipped as `0.43.1`
  through `0.43.4` closed every call site found in the full audit (direct
  manager calls and relation-traversal joins alike). This design is about
  the amplifier, not the individual slow queries.
- **Moving `_build_output` off the sweep entirely** (e.g. into its own Celery
  task per request). A larger architectural change; the transaction split
  gets the safety benefit without it.
- **Making `dry_run` actually dry.** It currently writes output files (see
  the `dry_run` section above). Pre-existing, unrelated to the transaction
  scope, and changing it could break whatever currently relies on inspecting
  `dry_run` output.
