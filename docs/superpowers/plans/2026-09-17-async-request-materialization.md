# Async Request Materialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /api/analytics/requests/` respond in near-constant time regardless of how many `ExtractTask`s a submission produces, by deferring task materialization to a background Celery task instead of doing it inline in the HTTP request.

**Architecture:** `create_request()` keeps its cheap, synchronous validation (`resolve_request_plan`, which already exposes `task_count` without writing anything) but stops calling `_build_tasks`/creating `RequestMap` rows inline. It creates the `Request` at a new `status=4` ("materializing") and schedules a new Celery task, `materialize_request_tasks`, via `transaction.on_commit` so it only fires once the row is actually committed. That task re-resolves the plan, runs the existing `_build_tasks`, bulk-creates `RequestMap`, and flips the request to `status=-1` ("queued") — the status value the existing completion sweep already looks for. The sweep's request-selection query already only considers `status=-1`/`0`, so a `status=4` request is automatically invisible to it with zero changes to that query; the race this design exists to prevent (the sweep marking a request "complete" before any `RequestMap` row exists) is closed structurally, not by adding a guard.

**Tech Stack:** Django 5.2, Celery (`@shared_task`, `transaction.on_commit`), existing `analytics.services`/`analytics.tasks.*` module layout.

**User decisions (already made):**
- New status value is `4` ("materializing"), not a renumbered `-2` (which is already the error state) — see spec for the full rationale.
- The raw submitted `datasets` spec is stored on `Request.data["dataset_specs"]` (new key, alongside the existing `data["datasets"]` resolved-summary key) so `materialize_request_tasks` only needs `request_id` as an argument — "you can use the request data to store anything else needed."
- `on_request_submitted` (the `post_save` signal) is left firing on `Request` creation as-is; reworking it to fire only after materialization is a deliberate, deferred follow-up once this ships and proves stable, not part of this plan.
- Design doc, already reviewed and approved: `docs/superpowers/specs/2026-09-17-async-request-materialization-design.md`.

---

## File Structure

- **`backend/analytics/services.py`** (modify) — `STATUS_LABELS` gains `4`; `create_request()` stops calling `_build_tasks`/creating `RequestMap` and instead creates the `Request` at `status=4` with `data["dataset_specs"]`, then schedules materialization; new `materialize_request(request)` function holds the deferred half of the old `create_request` body (re-resolve, `_build_tasks`, bulk-create `RequestMap`, flip to `status=-1`).
- **`backend/analytics/tasks/requests.py`** (create) — `materialize_request_tasks(request_id)`, a thin Celery wrapper around `materialize_request`, following the exact error-handling shape `analytics/tasks/ingest.py`'s `ingest_custom_boundary_task` already uses for the same "Request exists in a not-ready state, async task advances it" pattern.
- **`backend/analytics/tests/test_services.py`** (modify) — existing tests that assumed synchronous materialization gain an explicit materialization step; new tests cover the deferred-submission contract directly.
- **`backend/analytics/tests/test_views.py`** (modify) — same adjustment for the HTTP-level tests; `test_integrity_error_on_create_falls_back_to_get` moves to call `materialize_request_tasks` directly instead of `self.submit()`, since the code it exercises (`_get_or_create_task`'s fallback) no longer runs inline during the POST.
- **`backend/analytics/tests/test_tasks_requests.py`** (create) — tests for the new Celery task itself (not found, success, `NoExtractTasksError` → `status=-2`, unexpected exception → `status=-2` + re-raise, dispatch chain firing on success).
- **`backend/analytics/tests/test_manage_user_requests.py`** (create) — the regression test this whole design exists to enable: the completion sweep must never touch a `status=4` request.

---

### Task 1: Defer request materialization to a background Celery task

**Goal:** `create_request()` returns fast without creating `ExtractTask`/`RequestMap` rows; a new Celery task performs that work in the background and advances the request to `status=-1` once done.

**Files:**
- Modify: `backend/analytics/services.py`
- Create: `backend/analytics/tasks/requests.py`
- Modify: `backend/analytics/tests/test_services.py`
- Modify: `backend/analytics/tests/test_views.py`
- Create: `backend/analytics/tests/test_tasks_requests.py`

**Acceptance Criteria:**
- [ ] `create_request()` creates the `Request` at `status=4`, with `data["dataset_specs"]` holding the raw submitted `datasets` argument and `data["datasets"]` starting as `[]`, and creates zero `ExtractTask`/`RequestMap` rows.
- [ ] `create_request()` still raises `NoExtractTasksError` synchronously (unchanged behavior) when nothing in the submission resolves to a dataset.
- [ ] A new `materialize_request(request)` function builds the tasks, creates `RequestMap` rows, and updates the request to `status=-1` with `data["datasets"]` filled in with the resolved summary.
- [ ] `materialize_request_tasks(request_id)` (Celery task) calls `materialize_request`, and on success fires the same `chain(process_user_requests.si(), dispatch_processing_tasks.si())` the `post_save` signal fires on creation.
- [ ] On `Request.DoesNotExist`, the task logs and returns without raising.
- [ ] On `NoExtractTasksError` (a dataset became unavailable between submission and materialization), the task sets `status=-2` with the warnings recorded in `data["error"]`/`data["error_detail"]` and does not re-raise.
- [ ] On any other exception, the task sets `status=-2` with `data["error"]` and re-raises (so Celery's own failure tracking still sees it), matching `ingest_custom_boundary_task`'s existing pattern exactly.
- [ ] All existing tests in `test_services.py` and `test_views.py` that assumed synchronous materialization pass again, now calling materialization explicitly.

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_services analytics.tests.test_views analytics.tests.test_tasks_requests -v 2` → all tests pass (except the one pre-existing, unrelated failure noted below).

**Steps:**

- [ ] **Step 1: Update `STATUS_LABELS` and write the failing "deferred submission" tests**

In `backend/analytics/services.py`, update the dict:

```python
STATUS_LABELS = {
    -2: "error",
    -1: "queued",
    0: "processing",
    1: "completed",
    2: "preparing",
    3: "ingesting",
    4: "materializing",
}
```

Add these new tests to `backend/analytics/tests/test_services.py`, in the `CreateRequestTests` class (after `test_already_high_priority_task_is_not_rewritten`, before the two partition-pruning tests added in PR #25):

```python
    def test_submission_defers_task_materialization(self):
        created = self.create()

        self.assertEqual(created.request.status, 4)
        self.assertEqual(created.request.data["dataset_specs"], [self.spec()])
        self.assertEqual(created.request.data["datasets"], [])
        self.assertEqual(ExtractTask.objects.count(), 0)
        self.assertEqual(RequestMap.objects.count(), 0)
        # task_count is still reported immediately -- it comes from the
        # resolved plan (features x resources x options), not from counting
        # rows that don't exist yet.
        self.assertEqual(created.task_count, 8)

    def test_materialize_request_creates_tasks_and_queues_the_request(self):
        from analytics.services import materialize_request

        created = self.create()

        materialize_request(created.request)
        created.request.refresh_from_db()

        self.assertEqual(created.request.status, -1)
        self.assertEqual(ExtractTask.objects.count(), 8)
        self.assertEqual(
            RequestMap.objects.filter(request=created.request).count(), 8
        )
        self.assertEqual(
            created.request.data["datasets"][0]["dataset_name"], "ds"
        )

    def test_materialize_request_raises_when_nothing_resolves(self):
        from analytics.services import materialize_request

        created = self.create()
        # Simulate the dataset becoming unavailable between submission and
        # materialization running.
        Dataset.objects.filter(pk=self.dataset.pk).update(public=False)

        with self.assertRaises(NoExtractTasksError):
            materialize_request(created.request)
```

`Dataset` needs importing in the test file — check the existing `from datasets.models import Dataset, DatasetResource` import at the top of `test_services.py`; it's already there (used by `SubmissionFixture.setUp`), so no new import is needed.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_services.CreateRequestTests.test_submission_defers_task_materialization -v 2`
Expected: FAIL — `created.request.status` is whatever `_build_tasks` currently produces (not `4`), and `ExtractTask.objects.count()` is `8`, not `0`, because materialization still happens inline.

- [ ] **Step 3: Rewrite `create_request` and add `materialize_request`**

In `backend/analytics/services.py`, replace the existing `create_request` function body:

```python
def create_request(
    *,
    user,
    contact: str,
    name: str | None,
    feature_ids: list[int],
    datasets: list[dict],
    selection_label: str | None = None,
    selection_detail: str | None = None,
    source: str = "web",
) -> CreatedRequest:
    """Create a Request at status=4 (materializing) and defer ExtractTask/
    RequestMap creation to a background task.

    Validates the submission synchronously -- resolve_request_plan is
    read-only and already exposes task_count, so a bad dataset name or an
    empty selection still fails the request immediately, exactly as before.
    Only the expensive per-task materialization work (_build_tasks, one DB
    round-trip per (feature, resource, option) triple that isn't already
    pre-built) moves to the background -- a submission spanning enough
    time-series datasets can touch tens of thousands of triples, which was
    taking long enough to 504 even after the per-triple DB operations
    themselves were fixed to be fast (see analytics/tasks/processing.py and
    the resource_ids_hash partition-pruning fixes).

    Saving the Request fires the post_save receiver in analytics.signals,
    which is harmless at status=4: the completion sweep only ever looks at
    status=-1/0 (manage_user_requests.py), so it simply finds nothing to do
    for this request yet. The real "go process this" trigger is
    materialize_request_tasks firing the same dispatch chain once
    materialization finishes and the request becomes visible to the sweep
    for the first time.
    """
    plan = resolve_request_plan(user, feature_ids, datasets)

    if not plan.resolved:
        raise NoExtractTasksError(plan.warnings)

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


def materialize_request(request: Request) -> None:
    """The deferred half of create_request: build ExtractTasks, create
    RequestMap rows, and move the request from status=4 (materializing) to
    status=-1 (queued) -- the transition that makes it visible to the
    completion sweep for the first time.

    Re-resolves the plan against current state (feature_ids and
    dataset_specs, both stored on the request at submission time) rather
    than trusting a stale snapshot: dataset/feature visibility could
    theoretically change in the gap between submission and this running.
    Raises NoExtractTasksError if nothing resolves anymore -- the caller
    (materialize_request_tasks) is responsible for turning that into a
    status=-2 error on the request, the same way create_request turns it
    into an HTTP 400 when it happens synchronously at submission time.
    """
    plan = resolve_request_plan(
        request.user, request.data["feature_ids"], request.data["dataset_specs"]
    )
    all_task_ids, valid_datasets = _build_tasks(plan)

    if not all_task_ids:
        raise NoExtractTasksError(plan.warnings)

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

- [ ] **Step 4: Create the Celery task**

Create `backend/analytics/tasks/requests.py`:

```python
import logging

from celery import chain, shared_task

from analytics.models import Request
from analytics.services import NoExtractTasksError, materialize_request

logger = logging.getLogger(__name__)


@shared_task
def materialize_request_tasks(request_id):
    """Build ExtractTasks and RequestMap rows for a Request submitted at
    status=4 (materializing), then move it to status=-1 (queued).

    On success, explicitly fires the same dispatch chain
    analytics.signals.on_request_submitted fires on Request creation. That
    signal already ran when the Request was created, but harmlessly, since
    the completion sweep only looks at status=-1/0 and found nothing to do
    at status=4 -- this is the real "go process this" trigger, run once
    materialization has actually finished.

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

    from analytics.tasks.maintenance import (
        dispatch_processing_tasks,
        process_user_requests,
    )

    chain(process_user_requests.si(), dispatch_processing_tasks.si()).delay()
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_services.CreateRequestTests -v 2`
Expected: `test_submission_defers_task_materialization`, `test_materialize_request_creates_tasks_and_queues_the_request`, and `test_materialize_request_raises_when_nothing_resolves` all PASS.

- [ ] **Step 6: Fix the existing tests that assumed synchronous materialization**

These tests currently call `self.create()` and immediately assert `ExtractTask`/`RequestMap` rows exist. Each needs an explicit `materialize_request(...)` call after creating. In `backend/analytics/tests/test_services.py`:

Add the import at the top of the file (alongside the existing `from analytics.services import (...)` block):

```python
from analytics.services import (
    NoExtractTasksError,
    create_request,
    materialize_request,
    request_links,
    request_progress,
    requests_for_user,
    resolve_request_plan,
)
```

Update `CreateRequestTests.create` to materialize by default, since every existing test in this class except the three added in Step 1 expects the old fully-synchronous contract:

```python
    def create(self, **overrides):
        kwargs = dict(
            user=None,
            contact="a@example.com",
            name="My export",
            feature_ids=self.feature_ids,
            datasets=[self.spec()],
        )
        kwargs.update(overrides)
        created = create_request(**kwargs)
        materialize_request(created.request)
        created.request.refresh_from_db()
        return created
```

This means `test_submission_defers_task_materialization` (Step 1) must NOT use `self.create()` -- it needs the raw, unmaterialized `create_request()` call directly. Update it:

```python
    def test_submission_defers_task_materialization(self):
        created = create_request(
            user=None,
            contact="a@example.com",
            name="My export",
            feature_ids=self.feature_ids,
            datasets=[self.spec()],
        )

        self.assertEqual(created.request.status, 4)
        self.assertEqual(created.request.data["dataset_specs"], [self.spec()])
        self.assertEqual(created.request.data["datasets"], [])
        self.assertEqual(ExtractTask.objects.count(), 0)
        self.assertEqual(RequestMap.objects.count(), 0)
        self.assertEqual(created.task_count, 8)
```

`test_materialize_request_creates_tasks_and_queues_the_request` (Step 1) becomes redundant with `self.create()` now materializing by default -- delete it, since `test_creates_one_task_per_triple_and_one_request_map_row_each` (already existing, using `self.create()`) now covers exactly the same thing. Keep `test_materialize_request_raises_when_nothing_resolves` as-is; it already calls `materialize_request` explicitly after `self.create()`, which still works (materializing an already-materialized request's *original* plan a second time isn't what that test does -- it calls `self.create()` once, which now fully materializes, then calls `materialize_request` again after deactivating the dataset; the second call re-resolves from `request.data`, finds nothing, and must still raise). Re-read it once written to confirm this still makes sense; it does not need code changes.

No changes needed to `test_bulk_priority_bump_prunes_to_one_partition` or
`test_fallback_priority_bump_on_first_create_prunes_to_one_partition` (added
in PR #25) -- both already call `self.create()` and capture queries around a
*second* `self.create()` call, and `self.create()` materializing by default
means the captured queries still include the priority-bump UPDATE exactly as
before.

- [ ] **Step 7: Fix `RequestProgressAndLinksTests`**

In `backend/analytics/tests/test_services.py`, update `setUp`:

```python
class RequestProgressAndLinksTests(SubmissionFixture):
    def setUp(self):
        super().setUp()
        self.created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=self.feature_ids,
            datasets=[self.spec(extractTypes=["mean"], resources=["ds_2020"])],
        )
        materialize_request(self.created.request)
        self.created.request.refresh_from_db()
```

- [ ] **Step 8: Fix `test_views.py`'s HTTP-level tests**

In `backend/analytics/tests/test_views.py`, add the materialization call to the `submit` helper's callers rather than `submit` itself (some tests call `submit()` multiple times and need each call fully materialized before the next one runs, matching the real request/response cycle where each submission is independently processed):

```python
from analytics.services import materialize_request
```

Add this import alongside the existing `from analytics.models import ExtractTask, ProcessingOption, RequestMap` line.

Update `submit` to materialize inline, since every existing test in this file expects the full synchronous contract and none of them are testing the deferred behavior itself (that's covered in `test_services.py`):

```python
    def submit(self, **overrides):
        payload = {
            "email": "a@example.com",
            "featureIds": [self.feature.id],
            "datasets": [{"datasetName": self.dataset.name}],
        }
        payload.update(overrides)
        resp = self.client.post(
            self.url, data=payload, content_type="application/json"
        )
        if resp.status_code == 201:
            from analytics.models import Request

            req = Request.objects.get(id=resp.json()["id"])
            materialize_request(req)
        return resp
```

- [ ] **Step 9: Relocate `test_integrity_error_on_create_falls_back_to_get`**

This test mocks `ExtractTask.objects.get`/`.create` and asserts they're called during `self.submit()` -- but `_get_or_create_task` (what it's actually testing) no longer runs during the HTTP POST at all; it runs inside `materialize_request`, called by the new Celery task. Move it to call materialization directly instead of going through the view.

Note: this test already fails today on a clean `origin/main` checkout, for a
reason unrelated to this change (confirmed independently multiple times this
session: `mock_create.assert_called_once_with(...)` -- `Called 0 times`).
This step relocates it to the layer where the code it exercises now actually
lives; it does not fix the pre-existing failure, which stays exactly as
broken as it was before this plan, just at a different call site.

Replace the test in `backend/analytics/tests/test_views.py`:

```python
    def test_integrity_error_on_create_falls_back_to_get(self):
        # Simulates the race migration 0022's index exists for: two
        # concurrent materializations both miss the initial .get()
        # (DoesNotExist), one wins .create(), the other must hit
        # IntegrityError and recover by re-fetching the winner's row rather
        # than crashing. The initial .get() is forced to miss and .create()
        # is forced to collide; a real row (created ahead of the patch,
        # standing in for the "other request's" winning insert) is what the
        # fallback .get() must find.
        from analytics.models import Request
        from analytics.services import materialize_request

        existing = ExtractTask.objects.create(
            dataset_id=self.dataset.id,
            resource_ids=[self.resource.id],
            fm=self.fm,
            po=self.po,
            kwargs=None,
        )

        payload = {
            "email": "a@example.com",
            "featureIds": [self.feature.id],
            "datasets": [{"datasetName": self.dataset.name}],
        }
        resp = self.client.post(
            self.url, data=payload, content_type="application/json"
        )
        req = Request.objects.get(id=resp.json()["id"])

        with (
            mock.patch.object(
                ExtractTask.objects,
                "get",
                side_effect=[ExtractTask.DoesNotExist(), existing],
            ) as mock_get,
            mock.patch.object(
                ExtractTask.objects, "create", side_effect=IntegrityError
            ) as mock_create,
        ):
            materialize_request(req)

        mock_create.assert_called_once_with(
            dataset_id=self.dataset.id,
            resource_ids=[self.resource.id],
            fm=self.fm,
            po=self.po,
            kwargs=None,
        )
        expected_hash = RawSQL(
            "extract_tasks_resource_ids_hash(%s)", [[self.resource.id]]
        )
        expected_get_kwargs = {
            "dataset_id": self.dataset.id,
            "resource_ids": [self.resource.id],
            "resource_ids_hash": expected_hash,
            "fm": self.fm,
            "po": self.po,
            "kwargs__isnull": True,
        }
        self.assertEqual(mock_get.call_count, 2)
        for call in mock_get.call_args_list:
            self.assertEqual(call.kwargs, expected_get_kwargs)

        rm = RequestMap.objects.get(request_id=req.id)
        self.assertEqual(rm.task_id, existing.id)
        self.assertEqual(rm.dataset_id, self.dataset.id)
```

This still mocks `ExtractTask.objects.create`/`.get`, which means the
`submit()` helper's own materialization call (Step 8) cannot be used here --
this test needs the *unmaterialized* POST response. Since `submit()` now
always materializes on a 201, call `self.client.post` directly (as shown
above) instead of `self.submit()` for this one test.

- [ ] **Step 10: Run the full affected test suite**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_services analytics.tests.test_views analytics.tests.test_tasks_requests -v 1`
Expected: all tests pass except `test_integrity_error_on_create_falls_back_to_get`, which fails with the same pre-existing, unrelated assertion error it already has on `origin/main` today (`Expected 'create' to be called once. Called 0 times`).

`test_tasks_requests.py` doesn't exist yet at this point in the plan -- create it now:

```python
from unittest import mock

from django.test import TestCase

from analytics.models import ExtractTask, Request, RequestMap
from analytics.services import create_request
from analytics.tasks.requests import materialize_request_tasks
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ProcessingOption


class MaterializeRequestTasksTest(TestCase):
    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="ds", path="/data/ds", active=True, public=True
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
            public=True,
        )
        self.fc = FeatureCollection.objects.create(
            name="fc", path="/data/fc", active=True, public=True
        )
        self.feature = Feature.objects.create(shape="POINT(0 0)")
        self.fm = FeatMap.objects.create(fc=self.fc, geom=self.feature)

    def submit(self):
        return create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )

    def test_missing_request_logs_and_returns(self):
        # Must not raise for a request_id that doesn't exist (e.g. a retried
        # task after the request was somehow deleted).
        materialize_request_tasks("00000000-0000-0000-0000-000000000000")

    def test_success_creates_tasks_and_queues_the_request(self):
        created = self.submit()

        materialize_request_tasks(str(created.request.id))

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, -1)
        self.assertEqual(ExtractTask.objects.count(), 1)
        self.assertEqual(RequestMap.objects.count(), 1)

    def test_success_fires_the_dispatch_chain(self):
        created = self.submit()

        with mock.patch("analytics.tasks.requests.chain") as mock_chain:
            materialize_request_tasks(str(created.request.id))

        mock_chain.assert_called_once()
        mock_chain.return_value.delay.assert_called_once()

    def test_no_extract_tasks_sets_error_status(self):
        created = self.submit()
        Dataset.objects.filter(pk=self.dataset.pk).update(public=False)

        materialize_request_tasks(str(created.request.id))

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, -2)
        self.assertIn("error", created.request.data)
        self.assertIn("error_detail", created.request.data)

    def test_unexpected_exception_sets_error_status_and_reraises(self):
        created = self.submit()

        with mock.patch(
            "analytics.tasks.requests.materialize_request",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                materialize_request_tasks(str(created.request.id))

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, -2)
        self.assertEqual(created.request.data["error"], "boom")
```

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_services analytics.tests.test_views analytics.tests.test_tasks_requests -v 1`
Expected: all PASS except the one pre-existing failure noted above.

- [ ] **Step 11: Commit**

```bash
git add backend/analytics/services.py backend/analytics/tasks/requests.py backend/analytics/tests/test_services.py backend/analytics/tests/test_views.py backend/analytics/tests/test_tasks_requests.py
git commit -m "Defer request materialization to a background Celery task"
```

---

### Task 2: Regression and end-to-end tests for the materialization hand-off

**Goal:** Prove, with tests that exercise the real sweep code (not just the new code in isolation), that the design's core safety property holds: a `status=4` request is never touched by the completion sweep, and the full submit-to-complete flow still works once materialization hands off to it.

**Files:**
- Create: `backend/analytics/tests/test_manage_user_requests.py`

**Acceptance Criteria:**
- [ ] Running the sweep (`_manage_user_requests`) while a request sits at `status=4` leaves it completely untouched: no status change, no email sent, `_build_output` never called.
- [ ] A full flow -- submit, materialize, run the sweep twice (once to move it to `status=0`/pick up in-progress tasks, once to complete it once all tasks are done) -- ends with the request at `status=1` and download links present.

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_manage_user_requests -v 2` → all tests pass.

**Steps:**

- [ ] **Step 1: Confirmed entry point and email-sending hook (verified during planning)**

`_manage_user_requests(request_id=None, download_base="", frontend_base="", requests_dir="/requests", assets_dir="../assets", dry_run=False)` (`manage_user_requests.py:78`) is the sweep's outer function -- calling it with no arguments processes every queued/in-progress request, matching `process_user_requests` (the Celery task that calls it, `analytics/tasks/maintenance.py:95`). The email-sending hook is `_notify_user` (`manage_user_requests.py:243`), not `_send_request_email` -- confirmed directly against the file (an earlier draft of this plan guessed the wrong name). `_build_output` is at `manage_user_requests.py:341`. No further verification needed before writing the tests below; if any of these have moved by the time this task is implemented (e.g. another change landed in between), re-check against the current file rather than assuming this plan is still accurate.

- [ ] **Step 2: Write the failing regression test**

Create `backend/analytics/tests/test_manage_user_requests.py`:

```python
from unittest import mock

from django.test import TestCase

from analytics.management.commands.manage_user_requests import _manage_user_requests
from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from analytics.services import create_request, materialize_request
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection


class SweepIgnoresMaterializingRequestsTest(TestCase):
    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="ds", path="/data/ds", active=True, public=True
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
            public=True,
        )
        self.fc = FeatureCollection.objects.create(
            name="fc", path="/data/fc", active=True, public=True
        )
        self.feature = Feature.objects.create(shape="POINT(0 0)")
        self.fm = FeatMap.objects.create(fc=self.fc, geom=self.feature)

    def test_sweep_does_not_touch_a_materializing_request(self):
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )
        self.assertEqual(created.request.status, 4)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ) as mock_build_output, mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ) as mock_send_email:
            _manage_user_requests()

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, 4)
        self.assertEqual(ExtractTask.objects.count(), 0)
        self.assertEqual(RequestMap.objects.count(), 0)
        mock_build_output.assert_not_called()
        mock_send_email.assert_not_called()


class FullSubmissionToCompletionFlowTest(TestCase):
    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="ds", path="/data/ds", active=True, public=True
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
            public=True,
        )
        self.fc = FeatureCollection.objects.create(
            name="fc", path="/data/fc", active=True, public=True
        )
        self.feature = Feature.objects.create(shape="POINT(0 0)")
        self.fm = FeatMap.objects.create(fc=self.fc, geom=self.feature)

    def test_submit_materialize_sweep_reaches_completed(self):
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )

        materialize_request(created.request)
        created.request.refresh_from_db()
        self.assertEqual(created.request.status, -1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        created.request.refresh_from_db()
        # Not done yet -- the one ExtractTask hasn't run.
        self.assertEqual(created.request.status, 0)

        ExtractTask.objects.update(status=1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        created.request.refresh_from_db()
        self.assertEqual(created.request.status, 1)
```

- [ ] **Step 3: Run to verify these fail or pass for the right reasons**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_manage_user_requests -v 2`

`test_sweep_does_not_touch_a_materializing_request` should PASS immediately if Task 1 is correctly implemented (this is a pure verification test, no new production code needed for it to pass) -- if it fails, that means the sweep's existing `status=-1`/`status=0` filter (in `manage_user_requests.py`, lines 104-109 as read during planning) is somehow also matching `status=4`, which would mean Task 1's core safety claim is wrong and must be revisited before proceeding.

`test_submit_materialize_sweep_reaches_completed` exercises real production code end to end and should also PASS if Task 1 is correct; if `_manage_user_requests`'s actual signature or `_build_output`/`_notify_user`'s actual import paths differ from what Step 1 confirmed, fix the mock patch targets in this test to match, not the production code.

Expected: both PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/analytics/tests/test_manage_user_requests.py
git commit -m "Add regression tests proving the sweep ignores materializing requests"
```

---

## Self-Review Notes

**Spec coverage:** every section of the design doc has a corresponding task -- the state value (`4`, Task 1 Step 1), the `create_request`/`materialize_request` split (Task 1 Steps 3-4), the `dataset_specs` storage decision (Task 1 Step 3), the signal being left alone (documented in `create_request`'s new docstring, no code change), the error-handling shape (Task 1 Step 4), and every item in the design's Testing section (Task 1 Steps 1/10, Task 2).

**Known pre-existing gap, deliberately not fixed here:** `test_integrity_error_on_create_falls_back_to_get` fails on `origin/main` today for a reason unrelated to this plan. Task 1 Step 9 relocates it to the new call site without attempting to diagnose or fix the underlying assertion mismatch, to keep this plan scoped to async materialization.

**Follow-up, explicitly out of scope for this plan** (per the design doc): reworking `on_request_submitted` to fire only after materialization completes, rather than on Request creation. Revisit once this plan has shipped and proven stable in production.
