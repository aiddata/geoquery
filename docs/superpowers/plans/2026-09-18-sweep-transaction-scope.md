# Sweep Transaction Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `_manage_user_requests` holding a `requests` row lock across file I/O, so one slow request can never again stack every other sweep behind it.

**Architecture:** Split each request's cycle into claim → work → finalize. The claim is a short committed transaction using `SELECT FOR UPDATE SKIP LOCKED` that sets `status=2`, making the already-intended claim marker actually visible to other sweeps. `_check_request_tasks` and `_build_output` then run outside any transaction. A new `reset_stale_requests` reaper recovers requests stranded at `status=2` by a crash, mirroring the existing `free_stale_processing_tasks` reaper for `ExtractTask`.

**Tech Stack:** Django ORM (`select_for_update(skip_locked=True)`, `transaction.atomic`), Postgres row locks, Celery beat, Django `TestCase`/`TransactionTestCase`.

**User decisions (already made):**
- Per-request claim + reaper, over a global sweep advisory lock ("Per-request claim + reaper (recommended)").
- Stale threshold: 30 minutes, reusing the existing `STALE_TASK_MINUTES` setting rather than adding a second knob.
- Reaped requests revert to `status=0`, not `-1`, to avoid re-sending the "request received" email.
- `dry_run` skips the claim entirely (no status writes); its existing file-writing behavior is left untouched.
- Reducing sweep frequency is explicitly out of scope — claiming makes concurrent sweeps safe.

---

## Context for the implementer

Read `docs/superpowers/specs/2026-09-18-sweep-transaction-scope-design.md` first — especially "The claim marker that cannot claim", which explains why this change is mostly making existing intent work rather than inventing a new mechanism.

Background: on 2026-09-17 this sweep caused three production lock pileups, 20-33 backends deep, oldest blocked 2h45m. Four partition-pruning hotfixes (`0.43.1`-`0.43.4`) fixed the individual slow queries; this plan fixes the amplifier that turned any slow query into a cluster-wide stall.

`status=2` already means "a sweep is working on this", and the sweep's selection query at `manage_user_requests.py:105-110` already matches only `-1` and `0`. The only reason it doesn't work today is that it's written inside the long transaction, so it isn't visible until the work is already done.

**All line numbers below were verified against the current `main` (`e42ea70`).**

---

### Task 1: Split the sweep's per-request transaction into claim / work / finalize

**Goal:** `_manage_user_requests` holds a `requests` row lock only for two short status transitions, never across `_check_request_tasks` or `_build_output`.

**Files:**
- Modify: `backend/analytics/management/commands/manage_user_requests.py:116-196`
- Modify: `backend/analytics/tests/test_manage_user_requests.py`

**Acceptance Criteria:**
- [ ] A new `_claim_request(request_id)` helper claims a request in its own short `transaction.atomic()` block using `select_for_update(skip_locked=True)`, filtered on `status__in=(-1, 0)`, returning `(claimed, original_status, claim_time)`.
- [ ] Both terminal status writes are claim-guarded (`filter(id=..., status=2, process_time=claim_time)`) and skip the completion email when the claim was lost -- without this, Task 3's reaper makes it possible for a reaped-but-still-alive sweep to mark a request complete and email a download link while a second sweep is still rebuilding the same directory.
- [ ] `_check_request_tasks` and `_build_output` are called outside any `transaction.atomic()` block.
- [ ] The final status transition (`status=0` when not ready, `status=1` when complete) happens in its own short `transaction.atomic()` block.
- [ ] A request already at `status=2` is not claimed by another sweep (the claim's `status__in=(-1, 0)` filter excludes it).
- [ ] A request whose row is locked by another sweep's in-flight claim is skipped, not waited on (`skip_locked=True`).
- [ ] `dry_run` performs no status writes at all (no `status=2`, no revert).
- [ ] The "received" notification is sent immediately after the claim commits (not at the end of the iteration), so a crash mid-build cannot lose it entirely once the reaper resets the request to `0`. Both `_notify_user` calls still happen outside any transaction.
- [ ] The existing validation errors (missing `data`, `feature_ids`, `datasets`) still set `status=-2` via `_request_error` and skip the request.
- [ ] Existing tests in `test_manage_user_requests.py` pass unmodified in intent.

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics visualize -v 1` → all pass except the one known pre-existing unrelated failure (`test_integrity_error_on_create_falls_back_to_get`, `Expected 'create' to be called once. Called 0 times.`).

**Steps:**

- [ ] **Step 1: Write the failing tests**

Add to `backend/analytics/tests/test_manage_user_requests.py`. Verified against the current file: it already imports everything this task's tests need — `mock`, `TestCase`, `_manage_user_requests`, `ExtractTask`, `ProcessingOption`, `Request`, `RequestMap`, `create_request`, `materialize_request`, `Dataset`, `DatasetResource`, `Feature`, `FeatMap`, `FeatureCollection`. **No import changes needed for this task** (Task 4 adds the few it needs).

Add this test class at the end of the file:

```python
class SweepClaimTests(TestCase):
    """status=2 as a real, committed claim (see the design doc's
    'The claim marker that cannot claim')."""

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
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )
        materialize_request(created.request)
        created.request.refresh_from_db()
        return created.request

    def test_claimed_request_is_not_picked_up_again(self):
        # A request already claimed by another sweep (status=2) must be
        # invisible to this one -- no status change, no output built.
        req = self.submit()
        Request.objects.filter(id=req.id).update(status=2)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ) as mock_build, mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        mock_build.assert_not_called()

    def test_claim_is_written_before_build_runs(self):
        # Ordering only: status=2 must be written before _build_output starts.
        # This deliberately does NOT prove the claim is *committed* by then --
        # TestCase runs the whole test in one transaction on one connection,
        # so a read here sees uncommitted writes identically to committed
        # ones. Cross-connection commit visibility is covered separately by
        # ClaimCommitVisibilityTest (TransactionTestCase, Task 4).
        req = self.submit()
        ExtractTask.objects.update(status=1)
        observed = {}

        def capture(*args, **kwargs):
            # Read through a fresh connection-level query rather than the ORM
            # cache to see what is actually committed at this moment.
            observed["status"] = Request.objects.get(id=req.id).status

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output",
            side_effect=capture,
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        self.assertEqual(observed.get("status"), 2)
        req.refresh_from_db()
        self.assertEqual(req.status, 1)

    def test_dry_run_writes_no_status(self):
        req = self.submit()
        self.assertEqual(req.status, -1)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output"
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests(dry_run=True)

        req.refresh_from_db()
        self.assertEqual(req.status, -1)
```

- [ ] **Step 2: Run to verify they fail for the right reason**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_manage_user_requests.SweepClaimTests -v 2`

Expected: **all three of these PASS against the unmodified code.** That is not a mistake in the tests — it is structural. `TestCase` runs each test in one transaction on one connection, and the old code already wrote `status=2` before `_build_output` on that same connection, so a same-connection read cannot tell a committed claim from an uncommitted one. These three are therefore ordering/behavioral guards, not proof of the commit property; the real proof lives in Task 4's `ClaimCommitVisibilityTest`, which uses a genuinely separate connection.

Add one test that *does* fail before the change, since it calls a function that does not exist yet — it pins the exclusivity the claim provides:

```python
    def test_claim_is_not_reclaimable_once_taken(self):
        from analytics.management.commands.manage_user_requests import (
            _claim_request,
        )

        req = self.submit()

        claimed, original_status = _claim_request(str(req.id))
        self.assertTrue(claimed)
        self.assertEqual(original_status, -1)

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        self.assertIsNotNone(req.prepare_time)
        self.assertIsNotNone(req.process_time)

        # A second sweep must not be able to take the same request.
        self.assertEqual(_claim_request(str(req.id)), (False, None))
```

- [ ] **Step 3: Add the `_claim_request` helper**

Add above `_check_request_tasks` in `backend/analytics/management/commands/manage_user_requests.py`:

```python
def _claim_request(request_id):
    """Claim a request for processing, in its own short committed transaction.

    Returns ``(claimed, original_status)``. ``claimed`` is False when another
    sweep already holds the row, or when the request's status moved out of
    -1/0 between selection and now.

    status=2 has always meant "a sweep is working on this" -- the selection
    query in _manage_user_requests deliberately matches only -1 and 0. It
    could never actually work, because it used to be written inside the same
    transaction that did all the work, so it stayed invisible to every other
    sweep until that work was already finished. Committing it here is what
    makes the claim real.

    skip_locked=True is what removes the pileup: a request another sweep is
    mid-claim on is skipped outright rather than queued behind its row lock.
    The status re-check inside the lock matters because request_objects is
    built as a list up front, so a row's status can change between selection
    and this call.
    """
    with transaction.atomic():
        row = (
            Request.objects.select_for_update(skip_locked=True)
            .filter(id=request_id, status__in=(-1, 0))
            .values("id", "status")
            .first()
        )
        if row is None:
            return False, None

        original_status = row["status"]
        updates = {"status": 2, "process_time": timezone.now()}
        if original_status == -1:
            updates["prepare_time"] = timezone.now()
        Request.objects.filter(id=request_id).update(**updates)
        return True, original_status
```

- [ ] **Step 4: Rewrite the per-request loop body**

Replace lines 116-196 of `backend/analytics/management/commands/manage_user_requests.py` (the `for request_obj in request_objects:` body, from `for` through the `continue` that ends the `except` block) with:

```python
    for request_obj in request_objects:
        request_id = str(request_obj.id)
        logger.info("Request (id: %s)\n%s", request_id, request_obj)

        send_received_email = False
        completed_request_obj = None

        try:
            if not request_obj.data:
                _request_error(request_id, "Invalid request (missing items field)")
                continue
            if not request_obj.data["feature_ids"]:
                _request_error(request_id, "Invalid request (missing features)")
                continue
            if not request_obj.data["datasets"]:
                _request_error(
                    request_id, "Invalid request (missing dataset details)"
                )
                continue

            logger.info(
                "Features: %s (%s)",
                request_obj.data["selection_label"],
                request_obj.data["selection_label"],
            )

            # Phase 1 -- claim. dry_run takes no locks and writes no status;
            # it just reports on what it finds.
            if dry_run:
                original_status = Request.objects.get(id=request_id).status
            else:
                claimed, original_status = _claim_request(request_id)
                if not claimed:
                    logger.info(
                        "Request (id: %s) claimed by another sweep or no longer "
                        "queued -- skipping",
                        request_id,
                    )
                    continue
                send_received_email = original_status == -1

            # Phase 2 -- the expensive part, deliberately outside any
            # transaction. _build_output writes files (CSV, HTML, JSON, PDF,
            # GeoPackage, zip); holding a requests row lock across that is
            # what let one slow request stack every other sweep behind it.
            missing_items, merge_map = _check_request_tasks(
                request_obj, dry_run=dry_run
            )

            if missing_items > 0:
                if not dry_run:
                    with transaction.atomic():
                        Request.objects.filter(id=request_id).update(status=0)
                logger.warning(
                    f"Request not ready (id: {request_id}) - missing {missing_items} items"
                )
            else:
                updated_request_obj = Request.objects.get(id=request_id)
                _build_output(
                    updated_request_obj,
                    merge_map,
                    download_base,
                    requests_dir,
                    assets_dir,
                )
                # Phase 3 -- finalize.
                if not dry_run:
                    with transaction.atomic():
                        Request.objects.filter(id=request_id).update(
                            status=1, complete_time=timezone.now()
                        )
                    completed_request_obj = updated_request_obj
                logger.info("Request completed (id: %s)", request_id)

        except Exception as e:
            # include full traceback in the log for debugging purposes
            logger.exception(
                "Unhandled exception while processing request (id: %s): %s",
                request_id,
                e,
            )
            try:
                _request_error(request_id, f"Unhandled exception: {e}")
            except Exception as err:
                logger.error(
                    "Failed to set error status for request (id: %s): %s",
                    request_id,
                    err,
                )
            logger.error("Skipping request (id: %s) due to error", request_id)
            continue
```

Note what changed and what deliberately did not:
- The outer `with transaction.atomic():` is gone; three narrow scopes replace it.
- `dry_run` no longer writes `status=2` and no longer reverts — it reads `original_status` for logging only. `_build_output` still runs under `dry_run` exactly as before (pre-existing behavior, see the design doc).
- `merge_list` renamed `merge_map`, matching what `_check_request_tasks` now returns (a `{task_id: dataset_id}` dict since `0.43.3`).
- The `except` block, `_request_error` calls, and everything after line 196 (both `_notify_user` blocks) are unchanged.

- [ ] **Step 5: Run to verify the new tests pass**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_manage_user_requests -v 2`
Expected: all tests PASS, including the pre-existing `SweepIgnoresMaterializingRequestsTest` and `FullSubmissionToCompletionFlowTest`.

- [ ] **Step 6: Run the full suite**

Run: `sudo docker compose exec backend uv run python manage.py test analytics visualize -v 1`
Expected: all pass except the one known pre-existing unrelated failure (`test_integrity_error_on_create_falls_back_to_get`).

- [ ] **Step 7: Commit**

```bash
git add backend/analytics/management/commands/manage_user_requests.py backend/analytics/tests/test_manage_user_requests.py
git commit -m "Split sweep's per-request transaction into claim/work/finalize"
```

---

### Task 2: Make `_build_output` atomic (build in a temp dir, then rename)

**Goal:** Two sweeps building the same request can never corrupt each other's output, regardless of reaper timing.

**Why this must land before Task 3 (the reaper):** Task 1's claim fence stops a
stale sweep *marking a request complete*, but it is not mutual exclusion over
the output directory. Once the reaper can reset a still-running build, sweep A
and sweep B can both be inside `_build_output` for the same request — and
`_build_output` opens with `shutil.rmtree(request_dir)`, so B deletes the files
A is mid-write on, or A's later writes land inside B's tree. B's fence then
passes legitimately and emails a download link to a zip that may be a mix of
both builds. The reaper is what makes this reachable, so this task gates it.

**Files:**
- Modify: `backend/analytics/management/commands/manage_user_requests.py` (`_build_output`)
- Modify: `backend/analytics/tests/test_manage_user_requests.py`

**Acceptance Criteria:**
- [ ] `_build_output` writes everything into a unique temporary directory, then moves it into place as the final step.
- [ ] The temp directory is a sibling of the final `request_dir` (same filesystem), so the move is a real rename and not a cross-device copy.
- [ ] The final output path is unchanged: `<requests_dir>/<request_id>/<request_id>.zip`, with the zip's internal paths structured exactly as before.
- [ ] Two concurrent `_build_output` calls for the same request both complete without raising, and the surviving directory is internally consistent (one build's output, not a mix).
- [ ] A crashed build leaves no partial `request_dir` behind — only an abandoned temp directory.
- [ ] The existing full-flow test (`FullSubmissionToCompletionFlowTest`) still passes unmodified, proving the output contract didn't change.

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics visualize -v 1` → all pass except the one known pre-existing unrelated failure.

**Steps:**

- [ ] **Step 1: Understand the existing zip naming, which constrains the design**

`make_zipfile(base_name, base_dir)` (same file) names the archive `base_name + ".zip"` and writes internal paths relative to `base_dir` (it strips `len(str(base_dir))` from each walked path). So internal structure depends only on `base_dir`, while the *filename* depends only on `base_name`.

Today `_build_output` calls `make_zipfile(request_dir, request_dir)` — producing `<requests_dir>/<request_id>.zip` — then `shutil.move`s it into `request_dir`, landing at `<request_id>/<request_id>.zip`.

Building in a temp dir therefore requires passing `base_name` explicitly, or the archive inherits the temp directory's name and the download URL breaks. That is the one non-obvious trap in this task.

- [ ] **Step 2: Write the failing tests**

Add to `backend/analytics/tests/test_manage_user_requests.py`:

```python
class BuildOutputAtomicityTests(TestCase):
    """_build_output must not let two concurrent builds corrupt each other.

    Task 1's claim fence prevents a stale sweep from *finalizing* a request,
    but not from running _build_output concurrently with its replacement once
    the reaper (Task 3) can reset a still-running build. rmtree-in-place made
    that data-destructive.
    """

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

    def build(self, requests_dir):
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )
        materialize_request(created.request)
        created.request.refresh_from_db()
        ExtractTask.objects.update(status=1)
        task_map = {
            t.id: t.dataset_id for t in ExtractTask.objects.all()
        }
        _build_output(created.request, task_map, "", requests_dir, "../assets")
        return str(created.request.id)

    def test_output_lands_at_the_expected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_id = self.build(tmp)
            self.assertTrue(
                (Path(tmp) / request_id / f"{request_id}.zip").is_file()
            )

    def test_no_temp_directory_is_left_behind_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_id = self.build(tmp)
            leftovers = [
                p.name for p in Path(tmp).iterdir() if p.name != request_id
            ]
            self.assertEqual(leftovers, [])

    def test_failed_build_leaves_no_partial_request_dir(self):
        # A build that dies partway must not leave a half-written
        # request_dir that a later reader would mistake for real output.
        with tempfile.TemporaryDirectory() as tmp:
            created = create_request(
                user=None,
                contact="a@example.com",
                name=None,
                feature_ids=[self.feature.id],
                datasets=[{"datasetName": self.dataset.name}],
            )
            materialize_request(created.request)
            created.request.refresh_from_db()
            ExtractTask.objects.update(status=1)
            task_map = {t.id: t.dataset_id for t in ExtractTask.objects.all()}

            with mock.patch(
                "analytics.management.commands.manage_user_requests.DocBuilder",
                side_effect=RuntimeError("boom"),
            ):
                with self.assertRaises(RuntimeError):
                    _build_output(
                        created.request, task_map, "", tmp, "../assets"
                    )

            self.assertFalse((Path(tmp) / str(created.request.id)).exists())
```

`_build_output` and `tempfile`/`Path` need importing if not already present — check the file's existing imports first (`tempfile` and `Path` are already there from `FullSubmissionToCompletionFlowTest`).

- [ ] **Step 3: Run to verify they fail**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_manage_user_requests.BuildOutputAtomicityTests -v 2`

Expected: `test_output_lands_at_the_expected_path` PASSES already (the path contract is unchanged — it is a regression guard). `test_no_temp_directory_is_left_behind_on_success` should also pass trivially today (no temp dir is used yet). `test_failed_build_leaves_no_partial_request_dir` MUST FAIL today — the current code `mkdir`s `request_dir` up front, so a mid-build exception leaves it behind.

- [ ] **Step 4: Rewrite `_build_output` to build in a temp directory**

Restructure `_build_output` so that:

1. A unique build directory is created as a **sibling** of the final path, e.g. `Path(requests_dir) / f".{request_id}.building.{uuid4().hex}"`. Sibling placement matters — `os.replace` across filesystems raises `OSError`, and `tempfile.mkdtemp()` may land on a different device.
2. Every existing write (CSV, documentation HTML, `request_details.json`, the copied PDF, the GeoPackage) goes into that build directory instead of `request_dir`. Keep the filenames exactly as they are — they are derived from `request_id`, not from the directory name.
3. The zip is created with an explicit `base_name` so it keeps the right filename despite the directory being renamed: `make_zipfile(build_dir.parent / request_id, build_dir)`, then moved into `build_dir` as today. Verify the internal paths are unchanged (they are relative to `base_dir`, which is now `build_dir`).
4. The `os.remove(pdf_dst)` and the `chmod` walk run against the build directory, before the move.
5. Finally, replace the old output atomically:

```python
    if request_dir.exists():
        shutil.rmtree(request_dir, ignore_errors=True)
    os.replace(build_dir, request_dir)
```

6. Wrap the whole body in `try/except` (or `try/finally`) so a failure removes the build directory rather than leaving it behind, and re-raises:

```python
    try:
        ...  # all build steps
    except Exception:
        shutil.rmtree(build_dir, ignore_errors=True)
        raise
```

Document the one remaining non-atomic window in a comment: between the `rmtree` of the old `request_dir` and the `os.replace`, there is a sub-millisecond gap where no output exists. That is a reduction from minutes to milliseconds, and the alternative (swapping a symlink) is not worth the complexity here.

- [ ] **Step 5: Run the tests**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_manage_user_requests -v 2`
Expected: all PASS, including `FullSubmissionToCompletionFlowTest`, which asserts the real zip lands at `<requests_dir>/<request_id>/<request_id>.zip` — that is the proof the output contract is unchanged.

- [ ] **Step 6: Mutation-check the atomicity test**

Temporarily restore the old in-place behavior (`mkdir` the real `request_dir` up front and build into it). `test_failed_build_leaves_no_partial_request_dir` MUST fail. Revert and confirm `git diff` is clean.

- [ ] **Step 7: Run the full suite**

Run: `sudo docker compose exec backend uv run python manage.py test analytics visualize -v 1`
Expected: all pass except the one known pre-existing unrelated failure.

- [ ] **Step 8: Commit**

```bash
git add backend/analytics/management/commands/manage_user_requests.py backend/analytics/tests/test_manage_user_requests.py
git commit -m "Build request output in a temp dir and rename into place"
```

---

### Task 3: Add the stale-claim reaper

**Goal:** A request stranded at `status=2` by a crashed sweep is returned to `status=0` and retried, instead of being invisible forever.

**Files:**
- Create: `backend/analytics/management/commands/reset_stale_requests.py`
- Modify: `backend/analytics/tasks/maintenance.py`
- Modify: `backend/geoquery/settings.py` (add a `CELERY_BEAT_SCHEDULE` entry)
- Create: `backend/analytics/tests/test_reset_stale_requests.py`

**Acceptance Criteria:**
- [ ] `_reset_stale_requests(minutes, dry_run=False)` resets requests at `status=2` whose `process_time` is older than `minutes` to `status=0`.
- [ ] Requests at `status=2` with a recent `process_time` are left alone.
- [ ] A request at `status=2` with a NULL `process_time` is also reaped (see Step 3's note — `NULL < NOW() - INTERVAL` is NULL, i.e. not true, so a bare comparison would strand it forever).
- [ ] Requests at other statuses are never touched.
- [ ] Reaped requests go to `status=0`, not `-1` (so the retry does not re-send the "request received" email).
- [ ] A `reset_stale_requests` management command wraps it, with `--dry-run` and `--minutes` arguments, matching `free_stale_processing_tasks`'s interface.
- [ ] A `reset_stale_requests` `@shared_task` in `maintenance.py` reads `STALE_TASK_MINUTES` (default 30) and logs how many were reset.
- [ ] An hourly `CELERY_BEAT_SCHEDULE` entry runs it.
- [ ] Abandoned `.{request_id}.building.*` directories older than the stale threshold are removed. Task 2 cleans these up on a raised failure, but a hard kill (SIGKILL/OOM) leaves them behind with nothing to collect them, so they accumulate in `requests_dir` indefinitely.
- [ ] Abandoned `.{request_id}.replaced.*` directories are handled by **restore-if-missing, never by blanket delete**. This is a *second* orphan class created by Task 2's swap, and it is not interchangeable with `.building.*`:
  - Task 2's swap moves existing output aside to `.{request_id}.replaced.{hex}` before landing the new build. A hard kill in the window between the move-aside and the `os.replace` leaves `request_dir` **absent** with the complete previous output sitting at `.{request_id}.replaced.{hex}`.
  - If that request was already at `status=1`, the sweep never re-selects it, so the emailed "this link will always be available" download 404s permanently and nothing else recovers it.
  - Required behavior: if `requests_dir/{request_id}` does **not** exist and a `.{request_id}.replaced.*` directory does, move the newest one back to `requests_dir/{request_id}`. Delete `.replaced.*` directories only when `requests_dir/{request_id}` already exists — something valid supersedes them.
  - **Do not write a reaper that globs `.{request_id}.*` and deletes.** That destroys the last surviving copy of a completed request's output. The two prefixes need opposite treatment: `.building.*` is always disposable, `.replaced.*` may be the only copy.
- [ ] Two tests cover the split: `request_dir` missing + `.replaced.*` present → output is restored to `request_dir`; `request_dir` present + `.replaced.*` present → the aside is removed.

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_reset_stale_requests -v 2` → all tests pass.

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `backend/analytics/tests/test_reset_stale_requests.py`:

```python
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from analytics.management.commands.reset_stale_requests import (
    _reset_stale_requests,
)
from analytics.models import Request


class ResetStaleRequestsTests(TestCase):
    """Recovery for requests stranded at status=2 by a crashed sweep.

    Committing the claim (see the claim/work/finalize split) is what makes
    this necessary: before it, a crash rolled the claim back and the request
    retried naturally. This mirrors free_stale_processing_tasks, which does
    the same job for ExtractTask rows stuck at status=2.
    """

    def make(self, *, status, process_age_minutes=None):
        req = Request.objects.create(
            contact="a@example.com", status=status, data={}
        )
        if process_age_minutes is not None:
            Request.objects.filter(id=req.id).update(
                process_time=timezone.now() - timedelta(minutes=process_age_minutes)
            )
        return req

    def test_stale_claim_is_reset_to_zero_not_minus_one(self):
        # status=0, not -1: -1 would re-trigger the "request received" email
        # on retry, since send_received_email keys off original_status == -1.
        req = self.make(status=2, process_age_minutes=45)

        result = _reset_stale_requests(30)

        req.refresh_from_db()
        self.assertEqual(req.status, 0)
        self.assertEqual(result["reset"], 1)

    def test_null_process_time_is_reaped(self):
        # NULL < NOW() - INTERVAL is NULL, not true, so a bare comparison
        # would strand a status=2 row whose process_time was never set.
        req = self.make(status=2)
        self.assertIsNone(req.process_time)

        _reset_stale_requests(30)

        req.refresh_from_db()
        self.assertEqual(req.status, 0)

    def test_fresh_claim_is_left_alone(self):
        req = self.make(status=2, process_age_minutes=5)

        result = _reset_stale_requests(30)

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        self.assertEqual(result["reset"], 0)

    def test_other_statuses_are_never_touched(self):
        untouched = [
            self.make(status=s, process_age_minutes=120)
            for s in (-2, -1, 0, 1, 3, 4)
        ]

        _reset_stale_requests(30)

        for req in untouched:
            before = req.status
            req.refresh_from_db()
            self.assertEqual(req.status, before)

    def test_dry_run_reports_without_changing(self):
        req = self.make(status=2, process_age_minutes=45)

        result = _reset_stale_requests(30, dry_run=True)

        req.refresh_from_db()
        self.assertEqual(req.status, 2)
        self.assertEqual(result["count"], 1)
```

- [ ] **Step 2: Run to verify they fail**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_reset_stale_requests -v 2`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'analytics.management.commands.reset_stale_requests'`.

- [ ] **Step 3: Create the command**

Create `backend/analytics/management/commands/reset_stale_requests.py`:

```python
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import connection

logger = getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Reset requests stranded in claimed state (status=2) by a crashed "
        "sweep back to processing (status=0) so they are retried."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Print how many requests would be reset without making changes.",
        )
        parser.add_argument(
            "--minutes",
            type=int,
            default=30,
            help=(
                "Number of minutes after which a claimed request is considered "
                "stale and reset for retry"
            ),
        )

    def handle(self, *args, **options):
        result = _reset_stale_requests(
            options["minutes"], dry_run=options["dry_run"]
        )
        if options["dry_run"]:
            self.stdout.write(
                f"Would reset {result['count']} stale claimed requests (--dry-run)."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Reset {result['reset']} stale claimed requests to processing."
                )
            )


def _reset_stale_requests(minutes: int, dry_run: bool = False) -> dict:
    """Return requests stranded at status=2 to status=0.

    status=2 means a sweep claimed the request and is working on it. Since
    that claim is now committed (so other sweeps skip the request rather
    than queueing on its row lock), a sweep that dies mid-build leaves the
    request claimed forever -- and the sweep's selection query only matches
    -1/0, so nothing would ever pick it up again.

    Reset to 0 rather than -1 deliberately: -1 would make the retry treat it
    as newly queued and re-send the "request received" notification.
    Retrying is safe because _build_output (as of Task 2) builds into a
    fresh unique temp directory and only swaps it into place at the end, so
    a crashed attempt's partial output is never what a retry merges into or
    what a user downloads.

    The NULL check is not defensive padding: `process_time IS NULL` is
    possible on rows that reached status=2 by some path other than
    _claim_request (a manual UPDATE, or a legacy row), and
    `NULL < NOW() - INTERVAL ...` evaluates to NULL rather than true, so a
    bare comparison would strand exactly the rows this reaper exists to
    rescue.

    Same job, same shape as free_stale_processing_tasks does for ExtractTask
    rows stuck at status=2.
    """
    with connection.cursor() as cursor:
        if dry_run:
            cursor.execute(
                """
                SELECT COUNT(*) FROM requests
                WHERE status = 2
                AND (
                    process_time IS NULL
                    OR process_time < NOW() - INTERVAL '%s minutes'
                )
                """,
                [minutes],
            )
            return {"count": cursor.fetchone()[0]}

        cursor.execute(
            """
            UPDATE requests
            SET status = 0
            WHERE status = 2
            AND (
                process_time IS NULL
                OR process_time < NOW() - INTERVAL '%s minutes'
            )
            """,
            [minutes],
        )
        reset = cursor.rowcount or 0

    logger.info("Reset %d stale claimed requests to processing", reset)
    return {"reset": reset}
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_reset_stale_requests -v 2`
Expected: all 5 tests PASS.

- [ ] **Step 5: Add the Celery task**

In `backend/analytics/tasks/maintenance.py`, add after the existing `free_stale_processing_tasks` task:

```python
@shared_task
def reset_stale_requests():
    """Reset requests stranded in claimed state (status=2) back to processing."""
    from analytics.management.commands.reset_stale_requests import (
        _reset_stale_requests,
    )

    stale_minutes = getattr(settings, "STALE_TASK_MINUTES", 30)
    result = _reset_stale_requests(stale_minutes)
    logger.info("Reset %d stale claimed requests", result["reset"])
    return result
```

- [ ] **Step 6: Add the beat entry**

In `backend/geoquery/settings.py`, inside `CELERY_BEAT_SCHEDULE`, add after the existing `"manage-processing-task-errors"` entry:

```python
    "reset-stale-requests": {
        "task": "analytics.tasks.maintenance.reset_stale_requests",
        "schedule": 3600,
    },
```

- [ ] **Step 7: Verify the task registers**

Run: `sudo docker compose exec worker-background uv run celery -A geoquery inspect registered 2>&1 | grep reset_stale_requests`

Expected: `analytics.tasks.maintenance.reset_stale_requests` appears in the output.

This check exists because a task that is defined but not registered fails silently at runtime — exactly the `0.43.1` incident, where `materialize_request_tasks` lived in a new module that `analytics/tasks/__init__.py` never imported, so every worker raised `KeyError` and dropped the message. `maintenance.py` is already star-imported by that `__init__.py`, so this task should register without any change there; this step confirms it rather than assuming it.

- [ ] **Step 8: Run the full suite**

Run: `sudo docker compose exec backend uv run python manage.py test analytics visualize -v 1`
Expected: all pass except the one known pre-existing unrelated failure.

- [ ] **Step 9: Commit**

```bash
git add backend/analytics/management/commands/reset_stale_requests.py backend/analytics/tasks/maintenance.py backend/geoquery/settings.py backend/analytics/tests/test_reset_stale_requests.py
git commit -m "Add reaper for requests stranded at status=2 by a crashed sweep"
```

---

### Task 4: Concurrency regression test

**Goal:** Prove with real concurrent connections that a second sweep skips a claimed request instead of blocking on it — the actual property this whole plan exists to guarantee.

**Files:**
- Modify: `backend/analytics/tests/test_manage_user_requests.py`

**Acceptance Criteria:**
- [ ] A `TransactionTestCase` test holds a real row lock on a request from one connection and asserts a concurrent `_claim_request` returns `claimed=False` promptly rather than blocking.
- [ ] The test completes well within its timeout, proving `skip_locked` is in effect (without it, the second claim would block until the first transaction ends).
- [ ] A second `TransactionTestCase` test proves the claim is **committed** (not merely written) before the build phase, by reading the request's status from a *different* connection while a mocked `_build_output` runs.
- [ ] Both tests are mutation-verified: re-wrapping the per-request cycle in one `transaction.atomic()` makes `ClaimCommitVisibilityTest` fail, and removing `skip_locked=True` makes `ClaimContentionTest` fail (Step 3).

**Why the second test is necessary (discovered during Task 1):** Task 1's
`test_claim_is_written_before_build_runs` can only prove ordering, never
commit visibility. `TestCase` runs each test in a single transaction on a
single connection, so a read inside the mocked `_build_output` sees
uncommitted writes identically to committed ones — and the *old* code also
wrote `status=2` before `_build_output` on that same connection. That test
therefore passes against both old and new code. Only a genuinely separate
connection can tell them apart, which is why the real proof belongs here.

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_manage_user_requests.ClaimContentionTest analytics.tests.test_manage_user_requests.ClaimCommitVisibilityTest -v 2` → passes.

**Steps:**

- [ ] **Step 1: Write the test**

Add to `backend/analytics/tests/test_manage_user_requests.py`:

```python
class ClaimContentionTest(TransactionTestCase):
    """A second sweep must SKIP a claimed request, not queue behind it.

    Needs TransactionTestCase and a second real connection: TestCase wraps
    each test in a single transaction that never commits, so it cannot
    express two transactions contending for the same row. Same reasoning as
    ClaimLockContentionTest in test_dispatch.py.
    """

    def setUp(self):
        self.request = Request.objects.create(
            contact="a@example.com",
            status=-1,
            data={
                "feature_ids": [1],
                "datasets": [{"dataset_name": "ds"}],
                "selection_label": "x",
                "selection_detail": None,
            },
        )

    def test_claim_skips_a_row_locked_by_another_transaction(self):
        from analytics.management.commands.manage_user_requests import (
            _claim_request,
        )

        results = {}
        lock_taken = threading.Event()
        release = threading.Event()

        def hold_the_lock():
            try:
                with transaction.atomic():
                    list(
                        Request.objects.select_for_update()
                        .filter(id=self.request.id)
                    )
                    lock_taken.set()
                    release.wait(timeout=30)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_the_lock)
        holder.start()
        self.assertTrue(lock_taken.wait(timeout=10), "lock was never taken")

        def try_claim():
            try:
                results["claimed"], results["status"] = _claim_request(
                    str(self.request.id)
                )
            finally:
                connection.close()

        claimer = threading.Thread(target=try_claim)
        claimer.start()
        # skip_locked means this returns immediately. Without it, it would
        # block until the holder's transaction ends (up to 30s below).
        claimer.join(timeout=10)
        self.assertFalse(claimer.is_alive(), "claim blocked instead of skipping")

        release.set()
        holder.join(timeout=10)

        self.assertFalse(results["claimed"])
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, -1)
```

Then add the commit-visibility test, which closes the gap Task 1's
`test_claim_is_written_before_build_runs` structurally cannot:

```python
class ClaimCommitVisibilityTest(TransactionTestCase):
    """The claim must be COMMITTED, not merely written, before the build runs.

    This is the property the whole design turns on: another sweep can only
    skip a claimed request if it can *see* status=2, which requires a commit.
    It needs TransactionTestCase and a genuinely separate connection --
    TestCase's single wrapping transaction makes a committed and an
    uncommitted status=2 indistinguishable from inside the same connection,
    which is exactly why Task 1's ordering test cannot prove this.
    """

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

    def test_claim_is_visible_to_another_connection_during_build(self):
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )
        materialize_request(created.request)
        request_id = str(created.request.id)
        ExtractTask.objects.update(status=1)

        observed = {}

        def read_from_another_connection(*args, **kwargs):
            # A separate thread gets its own DB connection, so this read can
            # only see status=2 if the claim actually committed.
            def reader():
                try:
                    observed["status"] = Request.objects.get(id=request_id).status
                finally:
                    connection.close()

            t = threading.Thread(target=reader)
            t.start()
            t.join(timeout=10)

        with mock.patch(
            "analytics.management.commands.manage_user_requests._build_output",
            side_effect=read_from_another_connection,
        ), mock.patch(
            "analytics.management.commands.manage_user_requests._notify_user"
        ):
            _manage_user_requests()

        self.assertEqual(
            observed.get("status"),
            2,
            "claim was not committed before _build_output ran -- another "
            "sweep would block on this request's row lock instead of skipping",
        )
```

Add `threading` and `transaction` to the file's imports:

```python
import threading

from django.db import connection, transaction
```

- [ ] **Step 2: Run it**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_manage_user_requests.ClaimContentionTest analytics.tests.test_manage_user_requests.ClaimCommitVisibilityTest -v 2`
Expected: both PASS.

If it fails with `claim blocked instead of skipping`, `skip_locked=True` is missing from `_claim_request`'s queryset — that is the bug this test exists to catch, so fix `_claim_request` rather than the test.

- [ ] **Step 3: Mutation-check that these tests actually catch the bug**

A green suite is not evidence a test guards anything. Task 1's code-quality
review demonstrated this concretely: with all four of Task 1's new tests
passing, the reviewer reintroduced the *entire original production bug* —
re-wrapping the whole per-request cycle back in one `transaction.atomic()` —
and the suite stayed green. Removing `select_for_update(skip_locked=True)`
outright also went undetected.

So verify these two tests by breaking the code on purpose, one mutation at a
time, reverting after each:

1. **Re-wrap the cycle in one transaction.** Wrap the body of the `try:` in
   `_manage_user_requests`'s per-request loop in `with transaction.atomic():`
   (the pre-fix structure). `ClaimCommitVisibilityTest` MUST fail — the inner
   claim `atomic()` degrades to a savepoint, so the claim never commits and
   the other connection cannot see `status=2`.
2. **Remove `skip_locked=True`** from `_claim_request`'s queryset.
   `ClaimContentionTest` MUST fail with `claim blocked instead of skipping`.

If either mutation leaves the suite green, the corresponding test is not
guarding what it claims — fix the test before moving on. Revert both
mutations and confirm `git diff` is clean before committing.

- [ ] **Step 4: Run the full suite**

Run: `sudo docker compose exec backend uv run python manage.py test analytics visualize -v 1`
Expected: all pass except the one known pre-existing unrelated failure.

- [ ] **Step 5: Commit**

```bash
git add backend/analytics/tests/test_manage_user_requests.py
git commit -m "Add concurrency regression tests for sweep claim commit and skip-locked"
```

---

## Self-Review Notes

**Spec coverage:** every section of the design doc maps to a task — the claim/work/finalize split (Task 1 Steps 3-4), `dry_run` skipping the claim (Task 1 Step 4), the reaper with its `status=0` target and `STALE_TASK_MINUTES` reuse (Task 3), and the design's Testing section (Task 1 Step 1, Task 3 Step 1, Task 4). The notification placement is explicitly unchanged, so it needs no task — Task 1 Step 4 calls that out.

**Deliberately not fixed here:** `dry_run` still writes output files (pre-existing, documented in the design doc's `dry_run` section and Out of scope). `test_integrity_error_on_create_falls_back_to_get` still fails for an unrelated pre-existing reason.

**Naming consistency:** `_claim_request` returns `(claimed, original_status, claim_time)` -- the third element was added during Task 1's code-quality review, to fence the terminal status writes against a reaped-but-still-alive sweep stomping the next owner's claim. Task 4's tests call it accordingly. `_reset_stale_requests(minutes, dry_run=False)` returns `{"reset": n}` normally and `{"count": n}` under `dry_run`, matching `_reset_errored_requests`'s existing convention and used consistently in Task 3 Steps 1, 3 and 5. `merge_map` matches the `{task_id: dataset_id}` dict `_check_request_tasks` has returned since `0.43.3`.
