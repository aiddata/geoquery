# Async Request Materialization — Design

## Problem

`RequestView.post` → `create_request()` does all of its work synchronously inside
the HTTP request: `resolve_request_plan()` (cheap, read-only), then
`_build_tasks()` (one DB round-trip per `(feature, resource, processing option)`
triple that isn't already pre-built), then `Request.objects.create()`, then
`RequestMap.objects.bulk_create()`.

Two partition-pruning bugs in this path were already fixed (PRs #24/#25), which
took each individual per-task DB operation from multi-second down to
low-millisecond. That was necessary but not sufficient: a submission touching
even a modest number of time-series datasets (some of which carry 25-122
resources each — see `cru_ts_407_tmp_yearly_mean` at 122) can still produce tens
of thousands of `(feature, resource, po)` triples, and tens of thousands of
sequential round-trips at a few milliseconds each still adds up to multiple
seconds to low minutes — long enough to 504 at nginx's default timeout, and
confirmed happening in production with a "fairly small" submission (~5
time-series datasets, multiple processing options).

Goal: the HTTP response to a submission should be near-instant regardless of
how many tasks it ultimately produces. Per-task materialization work moves to
a background Celery task; the synchronous path keeps only what's genuinely
cheap and what the client needs to know immediately (does this submission
resolve to anything at all).

## Architecture

`RequestView.post` still calls `resolve_request_plan()` synchronously. It's
read-only and already computes `plan.task_count`, so the existing
"zero tasks resolvable" validation (`NoExtractTasksError`, e.g. an unknown
dataset name or no matching features) stays exactly where it is today, checked
before any response is sent — submissions that can't possibly produce a task
still fail fast and synchronously, with the same error surfaced to the client
they get today.

What moves to the background is the expensive part: `_build_tasks()` (the
per-triple lookup/create/priority-bump work) and the `RequestMap` bulk-create.

The endpoint creates the `Request` row immediately, at a new status value,
`status=4` ("materializing"), with the same `data` payload it writes today
(`selection_label`, `selection_detail`, `feature_ids`, `datasets`). It returns
right away — the client sees a real `Request` id and a submitted confirmation
without waiting on any per-task work.

A new Celery task, `materialize_request_tasks(request_id)`, does the deferred
work. `request_id` is the only argument -- everything else it needs is already
reachable from the `Request` row itself:

- `request.user` -- already a real FK field on `Request`, not something that
  needs passing separately or duplicating into `data`.
- `request.data["feature_ids"]` -- already stored as the raw submitted list
  today (unchanged by this design).
- The raw submitted `datasets` spec list -- **new**. `request.data["datasets"]`
  currently holds `valid_datasets`, the *post-resolution* summary
  (`dataset_name`, `dataset_type`, ...) built by `_build_tasks`, which is a
  different shape from the raw spec dicts `resolve_request_plan` expects as
  input (`datasetName`, `extractTypes`, `resources`, ...) and can't be
  converted back into it. `create_request` now also writes the original raw
  `datasets` argument into `request.data["dataset_specs"]` at creation time,
  alongside (not replacing) the existing `data["datasets"]` key, so nothing
  that already reads `data["datasets"]` changes shape.

This keeps the task signature minimal and means retrying/re-triggering
materialization (Celery redelivery, or manually via the admin/a management
command) only ever needs a `request_id` -- no arguments to reconstruct or lose
track of.

1. Re-resolve the plan via `resolve_request_plan(request.user, feature_ids,
   dataset_specs)`, reading those three inputs off the `Request` row as
   described above. Re-resolving against current state (rather than trusting
   `valid_datasets`, a resolved-at-submission-time snapshot) is deliberate:
   feature/dataset state could theoretically change in the gap between
   submission and materialization running.
2. Run `_build_tasks(plan)`, exactly as today.
3. Bulk-create `RequestMap` rows, exactly as today.
4. Update `Request.status` from `4` to `-1` ("queued") via `.update()` — this
   is the moment the request becomes visible to the normal processing sweep.
5. Explicitly fire the same dispatch chain `on_request_submitted` fires today:
   `chain(process_user_requests.si(), dispatch_processing_tasks.si()).delay()`.

## Why this doesn't reopen the race that motivated the state value

`_check_request_tasks` (the sweep's completion check) determines "done" by
counting `RequestMap` rows for the request and comparing against completed
`ExtractTask` rows. If a `Request` existed before its `RequestMap` rows did,
the check would see zero total tasks, compute zero missing, and mark the
request complete having done nothing — a real bug, not a cosmetic one (see
below).

This design prevents that by construction: the sweep's request-selection query
(`manage_user_requests.py`) only ever looks at `status=-1` and `status=0`.
`status=4` requests are invisible to it automatically, with no change needed
to that query. A request only enters `-1` once `materialize_request_tasks` has
already created every `RequestMap` row for it, in the same task, before the
status update runs — so by the time the sweep can see it, `RequestMap` is
already complete for it.

## Status values (existing, unchanged, for reference)

| Value | Meaning |
|---|---|
| `-2` | Error (has its own recovery path, `reset_errored_requests.py`) |
| `-1` | Queued, tasks exist, not yet swept |
| `0` | Received, sweep has checked at least once, not yet complete |
| `1` | Completed |
| `2` | Transient — sweep is actively checking this request right now |
| `3` | Awaiting custom boundary GeoJSON ingestion (a different, pre-existing async gap with the same shape as this one) |
| `4` | **New.** Materializing — `Request` row exists, `ExtractTask`/`RequestMap` creation not yet done |

`4` was chosen over reusing/renumbering `-2` specifically to avoid migrating
existing production error rows and every code path that checks for them; `-2`
and `3` are both pre-existing and untouched by this design.

## The `on_request_submitted` signal

`on_request_submitted` (`post_save` on `Request`, `created=True`) still fires
immediately when the `Request` row is created at `status=4`. This is harmless:
the sweep it kicks off only queries `status=-1`/`0`, so it simply won't find
anything to do for this particular request yet (it may still process *other*
genuinely-ready requests in the same pass, which is correct). The real
"go process this now" trigger moves to the end of
`materialize_request_tasks`, which fires the same chain explicitly — the
`4 → -1` transition is a bulk `.update()`, which doesn't re-fire `post_save`,
so this explicit call is required, not optional. The signal itself is left as
is rather than reworked, since doing so would add risk without benefit.

## Error handling

If `materialize_request_tasks` fails (e.g. a dataset was deactivated between
submission and materialization running), it sets `status=-2` with the error
recorded in `Request.data`, the same shape `_request_error` already writes
today — surfacing through the existing error-recovery path
(`reset_errored_requests.py`) with no new mechanism needed.

## Testing

- Submission test: `RequestView.post` returns quickly with `status=4`,
  `task_count` reflects the resolved plan, `data["dataset_specs"]` holds the
  raw submitted spec (distinct from the existing `data["datasets"]` resolved
  summary, which is unchanged), and — the test that actually proves the
  decoupling — zero `ExtractTask`/`RequestMap` rows exist at that point.
- Regression test for the race this design exists to close: run the sweep
  (`_manage_user_requests`) while a request sits at `status=4` and assert it
  is completely untouched — no status change, no email, no `_build_output`
  call.
- `materialize_request_tasks(request_id)`: builds the expected tasks, creates
  the matching `RequestMap` rows, transitions `4 → -1`, and fires the
  dispatch chain.
- Failure path: force an error inside materialization, assert `status=-2`
  with the error recorded in `data`.
- One full-flow test: submit → materialize → sweep picks it up → normal
  `-1 → 2 → 0/1` progression proceeds unchanged, confirming the handoff at
  the seam works end to end.

## Out of scope

- Reworking `on_request_submitted` to fire only on materialization completion
  rather than creation. Firing early is harmless today (the sweep's existing
  status filter means it simply finds nothing to do for a `status=4`
  request), so this isn't required for correctness. Deliberately deferred as
  a follow-up once this design has shipped and proven stable, not because it
  isn't worth doing -- moving it removes a redundant signal-then-explicit-call
  duplication, just not on the critical path for fixing the 504s.
- Any frontend changes to represent `status=4` distinctly to the user. Not
  discussed in this design and **not verified** either way: `request_progress()`
  (which the request detail page reads) delegates to the same
  `_check_request_tasks` the sweep uses, so a `status=4` request returns
  `(completed=0, total=0)` from it -- accurate, but how the frontend renders a
  0/0 ratio hasn't been checked. Worth a quick look during implementation
  (does `0/0` render as "0%", "100%", blank, or NaN?) even though the window
  is expected to be brief.
- Batching `_build_tasks` itself further (e.g. `bulk_create` for the fallback
  path instead of one `_get_or_create_task` call per triple) — this design
  moves the cost off the request path entirely, which was the stated goal;
  further speeding up materialization itself is a separate, independent
  optimization not required to solve the 504 problem.
