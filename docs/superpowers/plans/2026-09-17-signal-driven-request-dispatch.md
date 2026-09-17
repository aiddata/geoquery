# Signal-Driven Request Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `analytics/signals.py`'s `on_request_submitted` the single place that decides when a `Request` needs Celery's attention, replacing the explicit dispatch calls scattered across `services.py` and `tasks/requests.py`.

**Architecture:** `on_request_submitted` (post_save on `Request`) gets two conditions instead of firing unconditionally: `created and status==4` schedules `materialize_request_tasks`; `status in (-1, 0)` (any save, not just creation) schedules the `process_user_requests`/`dispatch_processing_tasks` chain. `materialize_request`'s final status transition switches from a bulk `.update()` to `request.save(...)` so the second condition actually fires — still inside the same `transaction.atomic()` block, so no change to the atomicity guarantee that closes the earlier re-run race. The explicit `transaction.on_commit(...)` calls in `create_request` and `materialize_request_tasks` are deleted; the signal now owns both.

**Tech Stack:** Django (signals, ORM, `transaction.on_commit`), Celery (`chain`, `shared_task`), Django `TestCase` (`captureOnCommitCallbacks`).

**User decisions (already made):**
- Scope is materialization-only; the custom-boundary ingest path (`status=3`) is not touched, but benefits automatically since it already transitions via `.save()`.
- The signal is gated on status, not deleted outright, so it stays a safety net for any future code path that creates a `Request` directly in a dispatchable state.
- `materialize_request`'s status transition switches back to `.save()` (reversing Task 1's earlier `.update()`, which was correct under the old unconditional-signal design but is no longer needed now that the signal is conditional).

---

## Context for the implementer

This plan is a small, self-contained follow-up to an already-shipped feature (async request materialization — see `docs/superpowers/specs/2026-09-17-async-request-materialization-design.md` for the full background if you want it, though you shouldn't need it). The design doc for *this* plan is `docs/superpowers/specs/2026-09-17-signal-driven-request-dispatch-design.md` — read it if anything below is unclear, especially the "Why this doesn't reopen the original race" section, which explains why gating the signal on status (rather than on creation) is safe: the periodic completion sweep (`_manage_user_requests` in `analytics/management/commands/manage_user_requests.py`) transitions `Request.status` exclusively via bulk `.update()` calls, which never fire `post_save` — so this change cannot cause the sweep's own internal state transitions to re-trigger dispatch. Only genuine external "this request just became ready" events (`Request.objects.create()`, and the two `.save()` call sites) can.

There are exactly three production files to change, plus two test files. All five changes are part of one coherent, interdependent unit — you can't ship a subset of them (e.g. deleting the explicit call in `create_request` without adding the signal condition would silently stop all materialization dispatch).

---

### Task 1: Move request dispatch from explicit calls to the post_save signal

**Goal:** `on_request_submitted` becomes the only place that schedules Celery work in response to a `Request`'s state, and the explicit dispatch calls in `services.py`/`tasks/requests.py` are removed.

**Files:**
- Modify: `backend/analytics/signals.py`
- Modify: `backend/analytics/services.py:387-411` (`create_request`), `backend/analytics/services.py:459-471` (`materialize_request`'s final block)
- Modify: `backend/analytics/tasks/requests.py`
- Create: `backend/analytics/tests/test_signals.py`
- Modify: `backend/analytics/tests/test_tasks_requests.py:60-66` (`test_success_fires_the_dispatch_chain`)

**Acceptance Criteria:**
- [ ] Creating a `Request` at `status=-1` or `status=0` fires `chain(process_user_requests.si(), dispatch_processing_tasks.si()).delay()` (via `transaction.on_commit`).
- [ ] Creating a `Request` at `status=3` or `status=4` does NOT fire that chain.
- [ ] Creating a `Request` at `status=4` schedules `materialize_request_tasks.delay(str(request.id))` (via `transaction.on_commit`).
- [ ] `create_request()` no longer contains an explicit `transaction.on_commit(...)` call or a deferred import of `analytics.tasks.requests` — that's the signal's job now.
- [ ] `materialize_request()`'s final status transition uses `request.save(update_fields=["status", "data"])`, still inside the existing `transaction.atomic()` block, not a bulk `.update()`.
- [ ] `materialize_request_tasks` no longer contains an explicit `chain(...).delay()` call or the `chain` import — dispatch happens as a side effect of `materialize_request`'s `.save()` call firing the signal.
- [ ] All existing tests in `test_services.py`, `test_views.py`, `test_tasks_requests.py`, `test_manage_user_requests.py` continue to pass, with `test_tasks_requests.py`'s `test_success_fires_the_dispatch_chain` updated to mock `analytics.signals.chain` instead of `analytics.tasks.requests.chain` (the latter no longer exists).

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics -v 1` → all pass except the one known pre-existing, unrelated failure (`test_integrity_error_on_create_falls_back_to_get`, `Expected 'create' to be called once. Called 0 times.` — predates this branch, out of scope).

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `backend/analytics/tests/test_signals.py`:

```python
from unittest import mock

from django.test import TestCase

from analytics.models import Request


class RequestDispatchSignalTests(TestCase):
    def test_creating_at_status_minus1_fires_the_dispatch_chain(self):
        with (
            mock.patch("analytics.signals.chain") as mock_chain,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=-1, data={})

        mock_chain.assert_called_once()
        mock_chain.return_value.delay.assert_called_once()

    def test_creating_at_status_0_fires_the_dispatch_chain(self):
        with (
            mock.patch("analytics.signals.chain") as mock_chain,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=0, data={})

        mock_chain.assert_called_once()
        mock_chain.return_value.delay.assert_called_once()

    def test_creating_at_status_3_does_not_fire_the_dispatch_chain(self):
        with (
            mock.patch("analytics.signals.chain") as mock_chain,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=3, data={})

        mock_chain.assert_not_called()

    def test_creating_at_status_4_does_not_fire_the_dispatch_chain_directly(self):
        with (
            mock.patch("analytics.signals.chain") as mock_chain,
            mock.patch(
                "analytics.tasks.requests.materialize_request_tasks.delay"
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=4, data={})

        mock_chain.assert_not_called()

    def test_creating_at_status_4_schedules_materialization(self):
        with (
            mock.patch(
                "analytics.tasks.requests.materialize_request_tasks.delay"
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            req = Request.objects.create(contact="a@example.com", status=4, data={})

        mock_delay.assert_called_once_with(str(req.id))

    def test_creating_at_status_3_does_not_schedule_materialization(self):
        with (
            mock.patch(
                "analytics.tasks.requests.materialize_request_tasks.delay"
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=3, data={})

        mock_delay.assert_not_called()
```

`Request.data` (`JSONField(blank=True, null=True)`) doesn't require a value -- omitting it just leaves it `None`. Pass `data={}` explicitly anyway in every call above, matching every production call site, since `on_request_submitted`'s existing production callers always pass a dict and a bare `None` is untested territory this plan doesn't need to explore.

- [ ] **Step 2: Run to verify they fail for the right reason**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_signals -v 2`

Expected: `test_creating_at_status_3_does_not_fire_the_dispatch_chain` and `test_creating_at_status_4_does_not_fire_the_dispatch_chain_directly` FAIL (`mock_chain.assert_not_called()` — currently called, since the signal is unconditional today). The `status=-1`/`status=0` tests and the two materialization-scheduling tests should already PASS or FAIL depending on whether `materialize_request_tasks` is currently imported by the signal at all (it isn't yet) — if `test_creating_at_status_4_schedules_materialization` fails with an import/attribute error rather than an assertion error, that's expected too; the point of this step is confirming the *new* behavior doesn't exist yet, not pinning every failure message exactly.

- [ ] **Step 3: Rewrite the signal**

Replace the full contents of `backend/analytics/signals.py`:

```python
from celery import chain
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Request


@receiver(post_save, sender=Request)
def on_request_submitted(sender, instance, created, **kwargs):
    """Schedule Celery work in response to a Request's saved state.

    Two independent conditions, not an if/elif -- a Request could in
    principle satisfy both across its lifetime, just never in the same
    save (status 4 only applies at creation; status -1/0 never applies at
    creation today, since both production create-paths start at 3 or 4).

    created and status==4: the request was just submitted and needs its
    ExtractTask/RequestMap rows built in the background (see
    analytics.services.create_request / materialize_request).

    status in (-1, 0), created or not: the request just became -- or still
    is -- something the periodic completion sweep should look at right
    away rather than waiting for the next scheduled tick. This fires for
    Request.objects.create() at status=-1/0 (no current production path
    does this, but it's a safety net for any future one that does), and
    for any .save() that lands a Request on -1 or 0 -- currently
    materialize_request's status=4->-1 transition and
    ingest_custom_boundary's status=3->-1 transition, both real .save()
    calls. The completion sweep itself never triggers this: it transitions
    status exclusively via bulk .update() (manage_user_requests.py), which
    Django never turns into a post_save signal, so this cannot cascade off
    the sweep's own -1->2->0/1 progression.

    Both branches defer to transaction.on_commit so a task can never start
    working on a Request before the transaction that made it visible has
    actually committed -- required here specifically because
    materialize_request's .save() runs inside its own transaction.atomic()
    block, so this receiver executes synchronously *inside* that block.
    """
    if created and instance.status == 4:
        from analytics.tasks.requests import materialize_request_tasks

        transaction.on_commit(
            lambda: materialize_request_tasks.delay(str(instance.id))
        )

    if instance.status in (-1, 0):
        from analytics.tasks.maintenance import (
            dispatch_processing_tasks,
            process_user_requests,
        )

        transaction.on_commit(
            lambda: chain(
                process_user_requests.si(), dispatch_processing_tasks.si()
            ).delay()
        )
```

- [ ] **Step 4: Run to verify the signal tests pass**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_signals -v 2`
Expected: all 6 tests PASS.

- [ ] **Step 5: Remove the explicit dispatch call from `create_request`**

In `backend/analytics/services.py`, `create_request` currently ends with (around line 400-411):

```python
    req = Request.objects.create(
        contact=contact,
        custom_name=name or None,
        user=user,
        source=source,
        status=4,
        data={
            "selection_label": selection_label,
            "selection_detail": selection_detail,
            "feature_ids": feature_ids,
            "datasets": [],
            "dataset_specs": datasets,
        },
    )

    # Deferred import: analytics.tasks.requests imports materialize_request
    # from this module, so a top-level import here would be circular. Same
    # pattern analytics.signals already uses for analytics.tasks.maintenance.
    from analytics.tasks.requests import materialize_request_tasks

    transaction.on_commit(lambda: materialize_request_tasks.delay(str(req.id)))

    return CreatedRequest(
        request=req, task_count=plan.task_count, warnings=plan.warnings
    )
```

Replace it with:

```python
    req = Request.objects.create(
        contact=contact,
        custom_name=name or None,
        user=user,
        source=source,
        status=4,
        data={
            "selection_label": selection_label,
            "selection_detail": selection_detail,
            "feature_ids": feature_ids,
            "datasets": [],
            "dataset_specs": datasets,
        },
    )

    return CreatedRequest(
        request=req, task_count=plan.task_count, warnings=plan.warnings
    )
```

Also update `create_request`'s docstring: it currently says "The real 'go process this' trigger is materialize_request_tasks firing the same dispatch chain once materialization finishes." Replace that closing paragraph with:

```python
    Saving the Request fires the post_save receiver in analytics.signals,
    which schedules materialize_request_tasks for this status=4 request
    (see analytics.signals.on_request_submitted) -- creating the Request is
    the only thing this function needs to do; the signal handles getting
    the background task scheduled once the transaction commits.
    """
```

(Replace the whole final paragraph of the existing docstring, from "Saving the Request fires..." to the end, with the text above.)

- [ ] **Step 6: Switch `materialize_request`'s final update to `.save()`**

In `backend/analytics/services.py`, `materialize_request`'s closing block currently reads:

```python
    with transaction.atomic():
        RequestMap.objects.filter(request=request).delete()
        RequestMap.objects.bulk_create(
            [
                RequestMap(request=request, task_id=task_id, dataset_id=dataset_id)
                for task_id, dataset_id in all_task_ids.items()
            ]
        )

        Request.objects.filter(id=request.id).update(
            status=-1,
            data={**request.data, "datasets": valid_datasets},
        )
```

Replace the final statement:

```python
    with transaction.atomic():
        RequestMap.objects.filter(request=request).delete()
        RequestMap.objects.bulk_create(
            [
                RequestMap(request=request, task_id=task_id, dataset_id=dataset_id)
                for task_id, dataset_id in all_task_ids.items()
            ]
        )

        request.status = -1
        request.data = {**request.data, "datasets": valid_datasets}
        request.save(update_fields=["status", "data"])
```

This still runs inside the same `transaction.atomic()` block -- the atomicity guarantee that closes the re-run race (delete/bulk_create/status-update as one unit, so the sweep can never observe a transient empty-`RequestMap` state) is unchanged. The only difference is `post_save` now fires for this transition (with `created=False`), which the new signal's second condition (`status in (-1, 0)`) picks up.

Also update `materialize_request`'s docstring: the paragraph starting "The delete, the bulk_create, and the status update run inside one transaction.atomic() block" still applies verbatim (the reasoning doesn't change) -- no docstring edit needed there. But its module-level context comment no longer needs updating either; leave the rest of the docstring as-is.

- [ ] **Step 7: Remove the explicit dispatch call from `materialize_request_tasks`**

Replace the full contents of `backend/analytics/tasks/requests.py`:

```python
import logging

from celery import shared_task

from analytics.models import Request
from analytics.services import NoExtractTasksError, materialize_request

logger = logging.getLogger(__name__)


@shared_task
def materialize_request_tasks(request_id):
    """Build ExtractTasks and RequestMap rows for a Request submitted at
    status=4 (materializing), then move it to status=-1 (queued).

    materialize_request's status update is a request.save(...) call, which
    fires analytics.signals.on_request_submitted -- that's what actually
    schedules the processing-dispatch chain once materialization finishes;
    this task doesn't need to do it explicitly.

    On failure sets status=-2 (error) and records the error message in
    request.data, the same shape analytics.tasks.ingest.
    ingest_custom_boundary_task already uses for this Request's sibling
    async-prep path (custom boundary ingestion, status=3 instead of 4).
    """
    try:
        req = Request.objects.get(id=request_id)
    except Request.DoesNotExist:
        logger.error("materialize_request_tasks: Request %s not found", request_id)
        return

    try:
        materialize_request(req)
        logger.info("Materialized tasks for request %s", request_id)
    except NoExtractTasksError as exc:
        logger.warning(
            "No extract tasks resolvable for request %s at materialization "
            "time: %s",
            request_id, exc.warnings,
        )
        Request.objects.filter(id=request_id).update(
            status=-2,
            data={**req.data, "error": str(exc), "error_detail": exc.warnings},
        )
        return
    except Exception as exc:
        logger.exception("Unexpected error materializing request %s", request_id)
        Request.objects.filter(id=request_id).update(
            status=-2, data={**req.data, "error": str(exc)}
        )
        raise
```

(This is identical to the current file except the `chain` import is gone and the trailing `chain(process_user_requests.si(), dispatch_processing_tasks.si()).delay()` block plus its deferred `analytics.tasks.maintenance` import are removed.)

- [ ] **Step 8: Fix `test_tasks_requests.py`'s dispatch-chain test**

In `backend/analytics/tests/test_tasks_requests.py`, `test_success_fires_the_dispatch_chain` currently reads:

```python
    def test_success_fires_the_dispatch_chain(self):
        created = self.submit()

        with mock.patch("analytics.tasks.requests.chain") as mock_chain:
            materialize_request_tasks(str(created.request.id))

        mock_chain.assert_called_once()
        mock_chain.return_value.delay.assert_called_once()
```

`analytics.tasks.requests.chain` no longer exists after Step 7 -- the dispatch now happens via the signal, in `analytics.signals`. Replace the mock target:

```python
    def test_success_fires_the_dispatch_chain(self):
        created = self.submit()

        with mock.patch("analytics.signals.chain") as mock_chain:
            materialize_request_tasks(str(created.request.id))

        mock_chain.assert_called_once()
        mock_chain.return_value.delay.assert_called_once()
```

This is still a meaningful black-box test: it calls the same public entry point (`materialize_request_tasks`) and asserts the same outward effect (the chain fires) -- only the internal mechanism producing that effect changed, and the test's mock target now points at where that mechanism actually lives.

- [ ] **Step 9: Run the full affected test suite**

Run: `sudo docker compose exec backend uv run python manage.py test analytics -v 1`

Expected: all tests pass except the one known pre-existing, unrelated failure (`test_integrity_error_on_create_falls_back_to_get`). Pay particular attention to:
- `analytics.tests.test_signals` (new, Step 1-4)
- `analytics.tests.test_services.CreateRequestTests` (especially `test_create_request_schedules_materialization_on_commit`, which mocks `analytics.tasks.requests.materialize_request_tasks.delay` -- this mock target is unchanged, since the signal imports and calls the same function, just from `analytics/signals.py` instead of `analytics/services.py`)
- `analytics.tests.test_tasks_requests` (Step 8's fix)
- `analytics.tests.test_manage_user_requests` (the full submit->materialize->sweep flow -- should be entirely unaffected, since it never asserts on *how* dispatch is scheduled, only on the request's eventual status)

If anything other than the one known failure breaks, investigate before proceeding -- don't paper over a real regression.

- [ ] **Step 10: Commit**

```bash
git add backend/analytics/signals.py backend/analytics/services.py backend/analytics/tasks/requests.py backend/analytics/tests/test_signals.py backend/analytics/tests/test_tasks_requests.py
git commit -m "Move request dispatch from explicit calls to the post_save signal"
```

---

## Self-Review Notes

**Spec coverage:** every section of the design doc has a corresponding step here -- the two-condition signal (Steps 1-4), removing `create_request`'s explicit call (Step 5), the `.update()`->`.save()` switch (Step 6), removing `materialize_request_tasks`'s explicit call (Step 7), and the one test that needed its mock target moved (Step 8). The design doc's "Not required — emergent side effect" note about `ingest_custom_boundary` needs no task, since no file there changes; Step 9's full-suite run is what actually proves that side effect doesn't break anything (`test_manage_user_requests`'s full-flow test exercises the custom-boundary-adjacent... actually the materialization-adjacent full flow; the custom-boundary path itself has no dedicated automated test in this codebase today, confirmed during design -- out of scope to add one here, since this plan doesn't touch `ingest.py` at all).

**Known pre-existing gap, deliberately not fixed here:** `test_integrity_error_on_create_falls_back_to_get` fails on `main` today for a reason unrelated to this plan (confirmed multiple times during the materialization work). Not touched by any step above.

**Type/signature consistency:** `materialize_request_tasks.delay(str(instance.id))` (signal) matches the argument shape `materialize_request_tasks(request_id)` already expects (a string, per every existing call site and test). `chain(process_user_requests.si(), dispatch_processing_tasks.si())` matches the exact call already used in the code being replaced -- same two task names, same `.si()`/`.delay()` shape, just relocated.
