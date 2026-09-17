# Signal-Driven Request Dispatch — Design

## Problem

The async request materialization work ([2026-09-17-async-request-materialization-design.md](2026-09-17-async-request-materialization-design.md)) deliberately left `on_request_submitted` (the `post_save` receiver on `Request`, `analytics/signals.py`) firing unconditionally on every `Request` creation, and instead added *explicit* dispatch calls at the two points where a request actually becomes ready for the processing sweep: `create_request()` schedules `materialize_request_tasks.delay(...)` via `transaction.on_commit(...)`, and `materialize_request_tasks` explicitly fires `chain(process_user_requests.si(), dispatch_processing_tasks.si()).delay()` on success. That was called out explicitly as a deferred follow-up once the design was stable in production: "moving it removes a redundant signal-then-explicit-call duplication."

Today, both production `Request.objects.create()` call sites (`services.py`'s `create_request`, status=4; `views.py`'s custom-boundary branch, status=3) create requests in a not-yet-ready state, so the signal's unconditional fire on creation is pure waste — it always finds nothing to do (the sweep only looks at `status in (-1, 0)`) and doubles Celery control-plane broadcast traffic on every single submission.

## Design

Replace the unconditional signal with two conditions, both firing through `transaction.on_commit(...)` (matching the existing pattern, safe whether or not the receiver runs inside a wrapping `atomic()` block):

```python
@receiver(post_save, sender=Request)
def on_request_submitted(sender, instance, created, **kwargs):
    if created and instance.status == 4:
        from analytics.tasks.requests import materialize_request_tasks
        transaction.on_commit(
            lambda: materialize_request_tasks.delay(str(instance.id))
        )
        return

    if instance.status in (-1, 0):
        from analytics.tasks.maintenance import (
            process_user_requests,
            dispatch_processing_tasks,
        )
        transaction.on_commit(
            lambda: chain(
                process_user_requests.si(), dispatch_processing_tasks.si()
            ).delay()
        )
```

This makes the signal the single source of truth for "a Request's state changed in a way that needs Celery attention," instead of scattering explicit dispatch calls across `services.py` and `tasks/requests.py`.

**Changes required:**

- `analytics/signals.py`: the two-condition receiver above.
- `services.py`'s `create_request()`: remove the explicit `transaction.on_commit(lambda: materialize_request_tasks.delay(...))` call and its deferred import — creation-time dispatch is now the signal's job.
- `services.py`'s `materialize_request()`: switch the final status transition from `Request.objects.filter(id=request.id).update(status=-1, data={...})` to `request.status = -1; request.data = {...}; request.save(update_fields=["status", "data"])`, still inside the existing `transaction.atomic()` block. `.update()` doesn't fire `post_save`; `.save()` does, with `created=False`, which the new second condition now handles correctly (the *first* condition only matches `created=True`, so this doesn't double-fire the materialize dispatch).
- `tasks/requests.py`'s `materialize_request_tasks`: remove the explicit `chain(...).delay()` call at the end and its deferred import — the signal now fires it as a side effect of `materialize_request`'s `.save()` call, still deferred to that transaction's commit.

**Not required — emergent side effect:** `ingest_custom_boundary` (the custom-boundary upload path, `analytics/ingest.py`) already transitions `3 → -1` via `req.save(update_fields=["data", "status"])`. It needs no code change; it starts satisfying the new second signal condition automatically, so custom-boundary uploads get picked up immediately instead of waiting for the next 5-minute `process_user_requests` beat tick. This was explicitly scoped out of the materialization-only follow-up as a file to touch — it isn't one, so it's in scope for free.

## Why this doesn't reopen the original race

The original signal was left unconditional specifically because moving it was extra risk without benefit *while the materialization design itself was unproven*. The safety property that design depends on — a `status=4` request must be invisible to the sweep until `RequestMap` rows exist for it — is enforced by the sweep's own query filter (`status in (-1, 0)`), not by anything about when the signal fires. This change doesn't touch that filter or the atomicity of `materialize_request`'s write path; it only changes *when Celery is told to look*, which is a liveness/efficiency concern, not a correctness one. Worst case if this were wrong: a request sits un-dispatched until the next periodic sweep tick — the exact behavior every request already tolerates today at status=3, and the exact behavior the current explicit-call design already relies on as swept correctly.

**No cascade risk from the sweep's own transitions:** `_manage_user_requests` transitions status via bulk `Request.objects.filter(id=request_id).update(...)` exclusively (confirmed by reading `manage_user_requests.py` in full) — `.update()` never fires `post_save`, so the sweep's own internal `2 → 0`, `2 → 1`, `* → -2` transitions cannot re-trigger this signal. Only genuine external "this request just became dispatchable" events do: `Request.objects.create()` and the two `.save()` call sites (`ingest_custom_boundary`, and `materialize_request` after this change).

**`reset_errored_requests.py`** uses a raw SQL `UPDATE requests SET status = -1 WHERE status = -2` (bypasses the ORM entirely, not just `.update()`) — unaffected by this change either way, exactly as unaffected as it is today. Already-known gap (recovering a materialization failure doesn't actually re-trigger materialization), out of scope for this change, tracked separately.

## Testing

- `analytics/tests/test_signals.py` (new): creating a `Request` at `status=-1` or `status=0` fires the dispatch chain; creating at `status=3` or `status=4` does not; creating at `status=4` fires `materialize_request_tasks.delay` with the new request's id (via `transaction.on_commit`, using `captureOnCommitCallbacks`, matching the pattern already established in `test_services.py`'s `test_create_request_schedules_materialization_on_commit`).
- Existing tests in `test_services.py`, `test_views.py`, `test_tasks_requests.py`, `test_manage_user_requests.py` (all from the materialization work) continue to pass unmodified in intent — `materialize_request`'s observable behavior (status ends at -1, data has the resolved `datasets`, idempotent on rerun) is unchanged; only the *mechanism* by which the trailing dispatch chain gets scheduled changes, which none of those tests assert on directly except the two call-site-specific ones being removed (`materialize_request_tasks`'s explicit `chain(...).delay()` call is deleted, so any test asserting on that call site's behavior moves to asserting on the signal instead — see `test_tasks_requests.py`'s `test_success_fires_the_dispatch_chain`, which currently mocks `analytics.tasks.requests.chain` and needs to move to asserting the signal fires via `materialize_request`'s `.save()`, not via a direct call inside `materialize_request_tasks` — that test's mock target no longer exists once the explicit call is removed).

## Out of scope

- Any change to `ingest_custom_boundary`/`ingest_custom_boundary_task` — they need no edits, as explained above.
- Fixing `reset_errored_requests.py`'s inability to actually recover a materialization failure — a separate, already-tracked gap.
- The MCP `tasks_total: 0` momentary-staleness observation from the materialization design's final review — unrelated to dispatch timing, not affected by this change.
