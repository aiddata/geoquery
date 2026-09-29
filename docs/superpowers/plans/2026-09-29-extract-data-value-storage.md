# Extract Data Value Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store single-value extract results in scalar columns, make nodata a real SQL NULL instead of the string `'None'`, and move completeness off array contents.

**Architecture:** `extract_data` gains three scalar columns beside its three existing typed array columns; a row populates one side or the other depending on `cardinality(resource_ids)`. Unused columns cost only a null-bitmap bit. Element-level NULL stops meaning "needs reprocessing" and starts meaning "nodata", so completeness moves to the task: a run either raises or it is done, and a retry recomputes every position. The existing 713.7M rows are discarded rather than migrated.

**Tech Stack:** Django 5.2 (CompositePrimaryKey), PostgreSQL 17 LIST-partitioned tables, Celery, pytest-style `django.test.TestCase`.

**User decisions (already made):**
- "Scalars + arrays side by side" — scalar columns for `n=1`, arrays retained for grouped tasks. Not scalar-only-with-one-row-per-position, and not arrays-only.
- "Minimal all-NULL row" — a nodata result writes a row with every value column NULL. Explicitly **not** the task-status-marker approach, and **not** omitting the row.
- "Task-level only, re-run all positions on retry" — no per-position `attempted` bitmask.
- "i think we can just truncate the extract data table and reset all extract tasks to status 0" — no data migration.
- "the other thing to fix before actually pushing any of that is the null value stuff" — writer fix ships **before** the cutover.
- "Truncate now, tune later" — `max_wal_size`/checkpoint tuning is out of scope.
- "Let it go" — the /stats completion history is not preserved.

**Spec:** `docs/superpowers/specs/2026-09-29-extract-data-value-storage-design.md`

---

## Deployment constraint — read before starting

**Tasks 1–6 are a single deployable unit.** Between Task 3 (writer emits scalars) and Task 4/5 (readers understand scalars) the system is internally inconsistent: production would write values no reader can see. Each task is individually committable and leaves the test suite green, but **do not deploy a partial sequence**. Merge 1–6 together.

Task 7 (the cutover command) ships in the same release but is *executed* afterwards, by hand, against production.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/analytics/models.py` | `ExtractData` field definitions and the docstring defining NULL semantics | 1, 6 |
| `backend/analytics/migrations/0027_extractdata_scalar_values.py` | Add the three scalar columns | 1 |
| `backend/analytics/migrations/0028_extractdata_drop_data_column.py` | Drop the now-redundant discriminator | 6 |
| `backend/analytics/tasks/processing.py` | Value classification, row assembly, completeness | 2, 3 |
| `backend/analytics/tasks/merge.py` | CSV/DataFrame reader | 4 |
| `backend/visualize/data.py` | Request/explore SQL and row aggregation | 5 |
| `backend/analytics/management/commands/reset_extract_data.py` | Cutover: truncate + per-partition reset | 7 |
| `backend/analytics/tests/test_models.py` | Schema-shape assertions on `ExtractData` | 1 |
| `backend/analytics/tests/test_processing.py` | Writer and completeness coverage | 2, 3, 6 |
| `backend/analytics/tests/test_merge.py` | Merge reader coverage | 4, 6 |
| `backend/visualize/tests/test_data.py` | Visualize reader coverage | 5, 6 |
| `backend/analytics/tests/test_reset_extract_data.py` | Cutover command coverage | 7 |

All test commands run from `backend/`. The project uses the `djm` alias for management commands (`djm <command>` in place of the full `docker compose exec` invocation).

## Test baseline

The dev stack runs in Docker and the local user is not in the docker group, so every command needs `sudo docker compose exec -T backend uv run python manage.py …` (sudo is passwordless; `-T` is required).

Two baselines, measured 2026-09-29 on this branch before any code changed:

- `test analytics visualize` → **215 tests, 1 failure**
- `test` (full suite) → **697 tests, 11 failures**

All 11 pre-date this work and must not be counted against any task:

```
analytics.tests.test_views.RequestViewStandardSubmissionTest.test_integrity_error_on_create_falls_back_to_get
catalog.tests.EndpointTests.test_autocomplete_respects_grants
catalog.tests.EndpointTests.test_coverage_endpoint_respects_grants
catalog.tests.EndpointTests.test_dataset_detail_widens_extract_types_for_granted_user
catalog.tests.EndpointTests.test_dataset_list_excludes_private_for_anonymous
catalog.tests.EndpointTests.test_dataset_list_includes_private_for_granted_user
catalog.tests.EndpointTests.test_submission_resolves_private_dataset_for_granted_user
features.tests.FeatureCollectionAutocompleteViewTests.test_excludes_inactive_and_private_collections
features.tests.FeatureCollectionAutocompleteViewTests.test_response_shape_matches_expected_fields
mcp_server.tests.test_tools_requests.SubmitRequestTests.test_confirmed_call_creates_the_request_with_source_mcp
public_api.tests.test_datasets.PublicDatasetCoverageViewTests.test_returns_datasets_covering_given_feature_ids
```

Tasks 1–5 verify against `analytics visualize`, which is sufficient because they only touch code those apps exercise. **Task 6 must run the full suite**: dropping `data_column` breaks `mcp_server/tests/factories.py`, which `analytics visualize` does not cover.

---

### Task 1: Add scalar value columns

**Goal:** `extract_data` has `int_value`, `float_value`, and `str_value` columns alongside the existing arrays, with nothing yet reading or writing them.

**Files:**
- Modify: `backend/analytics/models.py:209-252`
- Create: `backend/analytics/migrations/0027_extractdata_scalar_values.py`
- Modify: `backend/analytics/tests/test_models.py:84-93`

**Acceptance Criteria:**
- [ ] `ExtractData` declares `int_value` (BigInteger), `float_value` (Float), `str_value` (CharField max_length=100), all `blank=True, null=True`
- [ ] Migration 0027 applies cleanly and `\d extract_data` shows the three new columns
- [ ] `python manage.py makemigrations --check --dry-run` reports no pending model changes
- [ ] `ExtractDataArraysTest.test_value_arrays_exist` asserts both sides exist, rather than asserting the scalars are absent
- [ ] No new test failures beyond the pre-existing `test_views` one

**Verify:** `python manage.py test analytics visualize -v 2` → OK, no failures

**Steps:**

- [ ] **Step 1: Add the three fields to the model**

In `backend/analytics/models.py`, inside `class ExtractData`, insert the scalar fields directly after `data_column` and before `float_values`:

```python
    data_column = models.CharField(max_length=100, blank=True, null=True)
    # Single-value path: used when cardinality(resource_ids) == 1, which is
    # every non-grouped task. Carrying one number in a 1-element array costs
    # ~29 bytes against 8 for a scalar -- about 41% of the row -- and 713.7M
    # of 713.7M production rows were 1-element when this was measured.
    int_value = models.BigIntegerField(blank=True, null=True)
    float_value = models.FloatField(blank=True, null=True)
    str_value = models.CharField(max_length=100, blank=True, null=True)
    # Grouped path: used when cardinality(resource_ids) > 1, position-aligned
    # with the owning task's resource_ids.
    float_values = ArrayField(models.FloatField(null=True), blank=True, null=True)
    int_values = ArrayField(models.BigIntegerField(null=True), blank=True, null=True)
    str_values = ArrayField(models.CharField(max_length=100, null=True), blank=True, null=True)
```

- [ ] **Step 2: Write the migration**

Create `backend/analytics/migrations/0027_extractdata_scalar_values.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    """Add scalar value columns beside the existing arrays.

    ADD COLUMN with no default and NULL allowed is a catalog-only change in
    PostgreSQL 11+, so this is instant on the 713.7M-row partitioned table
    rather than a rewrite. It cascades to all 57 partitions automatically.
    """

    dependencies = [
        ("analytics", "0026_alter_extracttaskbuildprogress_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="extractdata",
            name="int_value",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="float_value",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="str_value",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
```

- [ ] **Step 3: Update the model test that asserts the scalars are absent**

`ExtractDataArraysTest.test_value_arrays_exist` in `backend/analytics/tests/test_models.py` was written to lock in migration 0019's removal of the scalar columns. Task 1 reintroduces them, so its three `assertNotIn` lines are now false by design. Replace the test body:

```python
    def test_value_arrays_exist(self):
        # Both sides of the row exist: scalars for single-resource tasks,
        # arrays for grouped ones. A row populates one side or the other.
        field_names = {f.name for f in ExtractData._meta.get_fields()}
        self.assertIn("float_values", field_names)
        self.assertIn("int_values", field_names)
        self.assertIn("str_values", field_names)
        self.assertIn("dataset_id", field_names)
        self.assertIn("float_value", field_names)
        self.assertIn("int_value", field_names)
        self.assertIn("str_value", field_names)
```

- [ ] **Step 4: Confirm the migration matches the model**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`

- [ ] **Step 5: Apply and confirm the suite is green**

Run: `python manage.py migrate analytics && python manage.py test analytics visualize -v 2`
Expected: migration `0027_extractdata_scalar_values... OK`, then the full suite passes with no failures.

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/0027_extractdata_scalar_values.py backend/analytics/tests/test_models.py
git commit -m "Add scalar value columns to extract_data

Every one of the 713.7M production rows is a 1-element array, which
costs ~29 bytes to carry one 8-byte value. Adds the scalar side; the
writer starts using it in a later commit."
```

---

### Task 2: Move completeness off array contents

**Goal:** A task completes when its run raised nothing, rather than when no array position is NULL — so a NULL can later mean "nodata" without the task looping forever.

**Files:**
- Modify: `backend/analytics/tasks/processing.py:263-286` (`_positions_needing_processing`)
- Modify: `backend/analytics/tasks/processing.py:474-496` (completion check in `_run_extract_task`)
- Modify: `backend/analytics/tests/test_processing.py:212-256` and `:257-300` — **both** rerun tests assert `call_log == ["r1"]`, not just the first

**Acceptance Criteria:**
- [ ] `_positions_needing_processing(n)` returns `set(range(n))` unconditionally and no longer takes `existing_rows`
- [ ] The `null_positions` scan and the `positions still null:` error fragment are deleted from `_run_extract_task`
- [ ] A retry recomputes every position, proven by the processor call log
- [ ] A task with a NULL array position still reaches `status=1` when the run raised nothing

**Verify:** `python manage.py test analytics.tests.test_processing -v 2` → OK

**Steps:**

- [ ] **Step 1: Update the test that asserts the skip optimization**

In `backend/analytics/tests/test_processing.py`, rename `test_rerun_only_reprocesses_null_positions` to `test_rerun_recomputes_every_position` and change the call-log assertion. Replace the final two assertions of that test:

```python
        # Every position is recomputed on a retry -- a NULL no longer means
        # "position i still needs work" (it will shortly mean "nodata"), so
        # there is nothing left to derive a skip list from.
        self.assertEqual(call_log, ["r0", "r1", "r2"])

        row.refresh_from_db()
        self.assertEqual(row.float_values, [0.0, 1.0, 2.0])
```

- [ ] **Step 2: Add a test proving a NULL position no longer blocks completion**

Append to `ProcessingTestCase` in `backend/analytics/tests/test_processing.py`:

```python
    def test_null_position_does_not_block_completion(self):
        # A run that raises nothing is complete, even if a processor returned
        # no value for some position. This is what lets a NULL mean "nodata"
        # rather than "retry me".
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)

        def sparse(geometry, path, **kw):
            if path.stem == "r1":
                return []  # legitimate success that yields no named result
            idx = int(path.stem[-1])
            return [("mean", float(idx))]

        with mock.patch.object(processing, "get_func", return_value=sparse):
            _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)
        self.assertIsNone(task.error)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python manage.py test analytics.tests.test_processing.ProcessingTestCase.test_rerun_recomputes_every_position analytics.tests.test_processing.ProcessingTestCase.test_null_position_does_not_block_completion -v 2`
Expected: FAIL — `AssertionError: ['r1'] != ['r0', 'r1', 'r2']` on the first, and `-1 != 1` on the second (the null position marks it incomplete).

- [ ] **Step 4: Make `_positions_needing_processing` unconditional**

Replace the whole of `_positions_needing_processing` in `backend/analytics/tasks/processing.py`:

```python
def _positions_needing_processing(n):
    """Every index into resource_ids (0..n-1). A retry recomputes all of them.

    This used to skip positions whose value was already non-NULL, reading an
    array NULL as "position i still needs work". That reading is gone: a NULL
    now means the extraction ran and found nodata, which is a final answer,
    not a request to retry. Telling those apart again would need a separate
    per-position marker.

    The only thing the skip bought was avoiding recomputation of
    already-successful resources on a grouped task's retry. That is free for
    single-position tasks (nothing to skip) and is paid only by grouped ones,
    and only when they actually fail. Do NOT reintroduce the skip without
    adding an explicit attempted-marker first -- without one it silently
    resurrects the infinite-retry bug for every nodata result.
    """
    return set(range(n))
```

- [ ] **Step 5: Update the call site and delete the completion scan**

In `_run_extract_task`, change only the call — **keep the `existing_rows` query**. The row-assembly block further down still reads it via `existing_by_name`, and removing it here would raise `NameError`. Task 3 deletes both together.

```python
        existing_rows = list(
            ExtractData.objects.filter(
                dataset_id=task.dataset_id, extract_task_id=task_id
            )
        )
        positions = _positions_needing_processing(n)
```

Then replace the completion block. Delete this:

```python
    failed_positions = {i for _, i, _ in failures}
    null_positions = set()
    for row in ExtractData.objects.filter(
        dataset_id=task.dataset_id, extract_task_id=task_id
    ):
        values = list(getattr(row, f"{row.data_column}_values") or [])
        values += [None] * (n - len(values))
        null_positions.update(i for i in range(n) if values[i] is None)

    incomplete_positions = failed_positions | null_positions
```

with this:

```python
    # A run that raised nothing is complete. A NULL value means the extraction
    # ran and found nodata -- a final answer, not an unfinished position (see
    # _positions_needing_processing).
    incomplete_positions = {i for _, i, _ in failures}
```

And in the error-message assembly below, delete the two lines referring to `null_positions`:

```python
    if null_positions - failed_positions:
        parts.append(f"positions still null: {sorted(null_positions - failed_positions)}")
```

- [ ] **Step 6: Confirm no dangling references**

The error assembly line `parts = [f"resource {rid}[{i}]: {exc!r}" for rid, i, exc in failures]` derives from `failures` directly and needs no change. Confirm the two deleted names are gone:

Run: `grep -n "failed_positions\|null_positions" backend/analytics/tasks/processing.py`
Expected: no output.

`existing_rows` is still referenced at this point — that is correct and Task 3 removes it.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python manage.py test analytics.tests.test_processing -v 2`
Expected: OK, 11 tests.

- [ ] **Step 8: Commit**

```bash
git add backend/analytics/tasks/processing.py backend/analytics/tests/test_processing.py
git commit -m "Move extract task completeness off array contents

Element-level NULL meant 'position i still needs work', which is why
nodata had to be stored as the string 'None' -- a real NULL would have
looped forever. Completion now depends only on whether the run raised,
and a retry recomputes every position.

Also drops two partition-scoped ExtractData queries per task that only
existed to feed the skip list."
```

---

### Task 3: Write nodata as NULL and single values as scalars

**Goal:** `_classify_value` returns `None` for nodata, column selection ignores nodata when picking a type, and a task writes either a scalar or an array depending on `cardinality(resource_ids)`.

**Files:**
- Modify: `backend/analytics/tasks/processing.py:37-51` (`_classify_value`)
- Modify: `backend/analytics/tasks/processing.py:415-461` (row assembly in `_run_extract_task`)
- Modify: `backend/analytics/tests/test_processing.py`
- Modify: `backend/analytics/models.py` — the `ExtractData` docstring says "The scalar columns are declared but not yet written", which this task makes false. Correct it here rather than deferring to Task 6; a docstring that contradicts the code is how the next reader gets it wrong.

**Acceptance Criteria:**
- [ ] `_classify_value(None)` returns `None`; no code path can produce the string `'None'`
- [ ] The `ExtractData` docstring no longer claims the scalar columns are unwritten
- [ ] A task with `len(resource_ids) == 1` writes `float_value`/`int_value`/`str_value` and leaves the arrays NULL
- [ ] A task with `len(resource_ids) > 1` writes the array position-aligned and leaves the scalars NULL
- [ ] A name whose first value is nodata but whose later values are floats produces a `float` row, not a `str` row
- [ ] An all-nodata task writes one row with every value column NULL and reaches `status=1`
- [ ] A run that produced nothing at all (every position raised) leaves a previous run's rows intact

**Verify:** `python manage.py test analytics.tests.test_processing -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `ProcessingTestCase` in `backend/analytics/tests/test_processing.py`:

```python
    # --- nodata is NULL, not the string "None" -----------------------------

    def test_nodata_is_stored_as_null_not_the_string_none(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", None)]
        ):
            _run_extract_task(task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, DONE)

        row = self.data_row(task, "mean")
        self.assertIsNone(row.float_value)
        self.assertIsNone(row.int_value)
        self.assertIsNone(row.str_value)
        self.assertIsNone(row.float_values)
        self.assertIsNone(row.int_values)
        self.assertIsNone(row.str_values)

    def test_single_resource_task_writes_scalar_not_array(self):
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", 1.5)]
        ):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_value, 1.5)
        self.assertIsNone(row.float_values)

    def test_grouped_task_writes_array_not_scalar(self):
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)

        def func(geometry, path, **kw):
            return [("mean", float(int(path.stem[-1])) * 10)]

        with mock.patch.object(processing, "get_func", return_value=func):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [0.0, 10.0, 20.0])
        self.assertIsNone(row.float_value)

    def test_total_failure_does_not_wipe_a_previous_runs_results(self):
        # The row set is replaced wholesale on each run, which would destroy
        # good data if a retry happened to fail on every position. A run that
        # produced nothing must leave the previous run's rows alone.
        resources = self.make_resources(1)
        task = self.make_task(resources, status=QUEUED)

        with mock.patch.object(
            processing, "get_func", return_value=lambda g, p, **kw: [("mean", 4.5)]
        ):
            _run_extract_task(task.id)
        self.assertEqual(self.data_row(task, "mean").float_value, 4.5)

        ExtractTask.objects.filter(id=task.id).update(status=PENDING)

        def always_fails(geometry, path, **kw):
            raise RuntimeError("boom")

        with mock.patch.object(processing, "get_func", return_value=always_fails):
            with self.assertRaises(RuntimeError):
                _run_extract_task(task.id)

        # Still there -- a transient failure must not cost us the good value.
        self.assertEqual(self.data_row(task, "mean").float_value, 4.5)

    def test_leading_nodata_does_not_type_the_row_as_str(self):
        # The bug this fixes: data_column was taken from the FIRST value seen,
        # so a nodata at position 0 typed the whole row 'str' and stringified
        # every real value after it. Masked until now only because every
        # production array happened to have exactly one element.
        resources = self.make_resources(3)
        task = self.make_task(resources, status=QUEUED)

        def func(geometry, path, **kw):
            if path.stem == "r0":
                return [("mean", None)]
            return [("mean", float(int(path.stem[-1])))]

        with mock.patch.object(processing, "get_func", return_value=func):
            _run_extract_task(task.id)

        row = self.data_row(task, "mean")
        self.assertEqual(row.float_values, [None, 1.0, 2.0])
        self.assertIsNone(row.str_values)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test analytics.tests.test_processing -v 2`
Expected: FAIL — `test_nodata_is_stored_as_null_not_the_string_none` fails with `str_values == ['None']`, and `test_single_resource_task_writes_scalar_not_array` fails with `float_value is None`.

- [ ] **Step 3: Rewrite `_classify_value`**

Replace the whole function in `backend/analytics/tasks/processing.py`:

```python
def _classify_value(value):
    """Return (column, coerced) for a raw processor result, or None for nodata.

    None is nodata, not a value: it becomes SQL NULL. Before this, the
    fallthrough below stringified it, and 210,329,319 production rows carried
    the literal text 'None' -- which merge.py's `values[i] is None` guard does
    not catch, so it reached user downloads as the string "None".

    int before float (order matters -- bool would otherwise be misfiled as
    int, but processors never return bool here so it's not a live concern),
    anything that isn't int/float/str is stringified rather than dropped.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return "int", value
    if isinstance(value, float):
        return "float", value
    if isinstance(value, str):
        return "str", value
    return "str", str(value)
```

- [ ] **Step 4: Add the column-selection helper**

Directly below `_classify_value` in `backend/analytics/tasks/processing.py`:

```python
def _column_for(values_by_pos):
    """Pick the value column for one name, from its first non-nodata value.

    Returns None when every position is nodata -- the row is still written, so
    that "we ran this and found nothing" stays distinguishable from "we never
    ran this", but no value column is populated.

    Deliberately the first NON-None value rather than simply the first: a
    leading nodata used to type the whole row 'str' and silently coerce every
    real value after it into the varchar array.
    """
    for i in sorted(values_by_pos):
        classified = _classify_value(values_by_pos[i])
        if classified is not None:
            return classified[0]
    return None
```

- [ ] **Step 5: Replace the row-assembly block**

In `_run_extract_task`, replace the entire block that begins `existing_by_name = {row.name: row for row in existing_rows}` and ends with `row.save()` — that is, everything from `existing_by_name` down to and including the `setattr(row, array_field, values)` / `row.save()` pair — with:

```python
        # Every position is recomputed (see _positions_needing_processing), so
        # this run's results are the complete picture for this task. Replace
        # the row set wholesale rather than merging into whatever a previous
        # run left behind. dataset_id prunes to one partition.
        #
        # Guarded on `produced` being non-empty: an empty one means EVERY
        # position raised this run, and wiping a previous run's good results
        # because of a transient failure would be strictly worse than keeping
        # them. The task goes to status=-1 either way and is recomputed in
        # full on retry. The old merge-based code got this for free via its
        # `elif not values_by_pos: continue` branch.
        #
        # A position that raised while others succeeded still lands as NULL
        # here, which is indistinguishable from nodata at the row level. That
        # is safe because the task is status=-1, and consumers gate on
        # status=1 (see manage_user_requests._check_request_tasks) -- so a
        # failed task's NULLs are never read as results.
        if produced:
            ExtractData.objects.filter(
                dataset_id=task.dataset_id, extract_task_id=task_id
            ).delete()

        rows = []
        for name, values_by_pos in produced.items():
            row = ExtractData(
                extract_task_id=task_id,
                dataset_id=task.dataset_id,
                name=name,
            )
            column = _column_for(values_by_pos)
            if column is not None:
                if n == 1:
                    classified = _classify_value(values_by_pos.get(0))
                    if classified is not None:
                        setattr(row, f"{column}_value", classified[1])
                else:
                    values = [None] * n
                    for i, value in values_by_pos.items():
                        classified = _classify_value(value)
                        if classified is not None:
                            if classified[0] != column:
                                logger.warning(
                                    "Task %s name %s position %d: %s value in a %s "
                                    "row; coercing. A name is assumed to produce one "
                                    "type across every position.",
                                    task_id, name, i, classified[0], column,
                                )
                            values[i] = classified[1]
                    setattr(row, f"{column}_values", values)
            rows.append(row)

        ExtractData.objects.bulk_create(rows)
        all_names = set(produced)
```

- [ ] **Step 6: Run the tests to verify they pass**

Two pre-existing tests break here, because the new assembly writes scalars and no longer writes `data_column` at all. Fix both now rather than deferring.

In `test_standard_task_single_resource_success`, replace its final assertion block:

```python
        row = self.data_row(task, "mean")
        self.assertEqual(row.float_value, 1.5)
        self.assertEqual(row.dataset_id, self.dataset.id)
```

In `test_grouped_task_all_resources_success_is_position_aligned`, replace its final assertion block:

```python
        mean_row = self.data_row(task, "mean")
        self.assertEqual(mean_row.float_values, [0.0, 10.0, 20.0])
        count_row = self.data_row(task, "count")
        self.assertEqual(count_row.int_values, [0, 1, 2])
```

Then run: `python manage.py test analytics.tests.test_processing -v 2`
Expected: OK, 15 tests.

- [ ] **Step 7: Commit**

```bash
git add backend/analytics/tasks/processing.py backend/analytics/tests/test_processing.py
git commit -m "Store nodata as NULL and single values as scalars

_classify_value returned ('str', 'None') for a nodata result, and 210.3M
production rows carried that string. merge.py's `is None` guard does not
catch it, so the text None reached user downloads.

Column selection now uses the first NON-None value, fixing a latent bug
where a leading nodata typed the whole row 'str' and coerced every real
value after it. Masked until now because every production array has
exactly one element; the 930 unbuilt 12-element pairs would have hit it."
```

---

### Task 4: Read scalars in merge

**Goal:** `merge.py` assembles output from whichever value column is populated, and a nodata result produces an empty cell rather than the text `None`.

**Files:**
- Modify: `backend/analytics/tasks/merge.py:225-243`
- Modify: `backend/analytics/tests/test_merge.py`

**Acceptance Criteria:**
- [ ] A row with `float_value=12.5` and NULL arrays yields `12.5` in the merged output
- [ ] A row with `float_values=[20.0, 0.0, 10.0]` still expands per-resource as today
- [ ] A row with every value column NULL contributes no cell, producing NaN
- [ ] No merged output can contain the string `"None"` from a nodata result

**Verify:** `python manage.py test analytics.tests.test_merge -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing tests**

Add to `MergeTaskResultsTestCase` in `backend/analytics/tests/test_merge.py`, using its existing `make_task` helper and `setUpTestData` fixtures:

```python
    # --- scalar rows and nodata -------------------------------------------

    def test_scalar_value_row_is_read(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="my_resource", path="r1.tif"
        )
        task = self.make_task([resource])
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            float_value=12.5,
        )

        status, df = merge_task_results({task.id: self.dataset.id})

        self.assertEqual(status, "Success")
        self.assertEqual(df.iloc[0]["my_resource.mean"], 12.5)

    def test_all_null_row_produces_no_column_not_the_string_none(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="my_resource", path="r1.tif"
        )
        task = self.make_task([resource])
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
        )

        status, df = merge_task_results({task.id: self.dataset.id})

        self.assertEqual(status, "Success")
        # The nodata row contributes no cell at all, so no such column is
        # assembled -- and critically the literal text "None" appears nowhere.
        self.assertNotIn("my_resource.mean", df.columns)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test analytics.tests.test_merge -v 2`
Expected: FAIL — `Unsupported data column type: None` raised from the `else` branch, because `data_column` is unset on these rows.

- [ ] **Step 3: Replace the data_column branch**

In `backend/analytics/tasks/merge.py`, replace this block:

```python
            for td in task_data:
                if td.data_column == "int":
                    values, coerce = td.int_values, int
                elif td.data_column == "float":
                    values, coerce = td.float_values, float
                elif td.data_column == "str":
                    values, coerce = td.str_values, str
                else:
                    raise Exception(f"Unsupported data column type: {td.data_column}")

                values = values or []
```

with:

```python
            for td in task_data:
                # Exactly one side of the row is populated: scalars when the
                # task covers one resource, arrays when it covers several. A
                # row with neither is a nodata result -- the record that the
                # extraction ran and found nothing -- and contributes no cells.
                if td.int_values is not None:
                    values, coerce = td.int_values, int
                elif td.float_values is not None:
                    values, coerce = td.float_values, float
                elif td.str_values is not None:
                    values, coerce = td.str_values, str
                elif td.int_value is not None:
                    values, coerce = [td.int_value], int
                elif td.float_value is not None:
                    values, coerce = [td.float_value], float
                elif td.str_value is not None:
                    values, coerce = [td.str_value], str
                else:
                    continue
```

- [ ] **Step 4: Remove the obsolete test**

`test_unsupported_data_column_raises` asserts behaviour that no longer exists — there is no discriminator to be unsupported. Delete that test method from `backend/analytics/tests/test_merge.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python manage.py test analytics.tests.test_merge -v 2`
Expected: OK. Existing array-based tests still pass because they set `float_values`/`int_values`/`str_values`, which the new branch checks first.

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/tasks/merge.py backend/analytics/tests/test_merge.py
git commit -m "Read scalar value columns in merge

Selects whichever side of the row is populated instead of branching on
data_column. A row with nothing populated is a nodata result and now
contributes no cell, so it becomes a genuine NaN rather than the string
'None' that 210.3M rows were feeding into user downloads."
```

---

### Task 5: Read scalars in visualize

**Goal:** The request and explore SQL cover scalar rows, which have NULL arrays and would otherwise unnest to nothing and vanish.

**Files:**
- Modify: `backend/visualize/data.py:88-143` (both SQL constants)
- Modify: `backend/visualize/data.py:185-191` (`_aggregate_data_rows` type branch)
- Modify: `backend/visualize/tests/test_data.py`

**Acceptance Criteria:**
- [ ] A scalar row appears in `build_request_data` output rather than being dropped by `unnest`
- [ ] A grouped array row still expands one output row per resource position
- [ ] `ed.data_column` appears in neither SQL constant nor in `_aggregate_data_rows`
- [ ] A row with every value column NULL yields a `None` value, not a crash

**Verify:** `python manage.py test visualize -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing test**

Add to `VisualizeDataTestCase` in `backend/visualize/tests/test_data.py`, using its existing `_make_request` helper and `setUpTestData` fixtures:

```python
    # --- scalar rows -------------------------------------------------------

    def test_build_request_data_scalar_row_is_not_dropped_by_unnest(self):
        # Scalar rows have NULL arrays, and unnest(NULL) yields no rows -- so
        # without the COALESCE wrapping, the whole row silently disappears
        # from the payload rather than failing loudly.
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds1-r1", label="Jan 2020", path="r1.tif"
        )
        task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id,
            fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
            float_value=3.25,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="count",
            int_value=7,
        )
        req = self._make_request(task)

        result = build_request_data(req)

        record = result["features"][str(self.feature.id)]
        self.assertEqual(record["ds1-r1.mean"], 3.25)
        self.assertIsInstance(record["ds1-r1.mean"], float)
        self.assertEqual(record["ds1-r1.count"], 7)
        self.assertIsInstance(record["ds1-r1.count"], int)

    def test_build_request_data_all_null_row_yields_none(self):
        resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds1-r1", label="Jan 2020", path="r1.tif"
        )
        task = ExtractTask.objects.create(
            resource_ids=[resource.id], dataset_id=self.dataset.id,
            fm=self.fm, po=self.po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean",
        )
        req = self._make_request(task)

        result = build_request_data(req)

        self.assertIsNone(result["features"][str(self.feature.id)]["ds1-r1.mean"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python manage.py test visualize -v 2`
Expected: FAIL — `KeyError: 'ds1-r1.mean'` in both new tests, because `unnest` over the NULL arrays yields zero rows and the record is never populated.

- [ ] **Step 3: Cover both shapes in both SQL constants**

In `backend/visualize/data.py`, in **both** `_REQUEST_EXTRACT_DATA_SQL` and `_EXPLORE_EXTRACT_DATA_SQL`, replace the lateral:

```sql
    CROSS JOIN LATERAL unnest(et.resource_ids, ed.float_values, ed.int_values, ed.str_values)
        WITH ORDINALITY AS u(resource_id, float_value, int_value, str_value, ord)
```

with:

```sql
    -- A row populates either the scalar side (one resource) or the array side
    -- (several). unnest(NULL) yields no rows, so a scalar row would vanish
    -- entirely without wrapping each scalar in a 1-element array first.
    CROSS JOIN LATERAL unnest(
            et.resource_ids,
            COALESCE(ed.float_values, ARRAY[ed.float_value]),
            COALESCE(ed.int_values,   ARRAY[ed.int_value]),
            COALESCE(ed.str_values,   ARRAY[ed.str_value])
        )
        WITH ORDINALITY AS u(resource_id, float_value, int_value, str_value, ord)
```

Then delete this line from **both** SELECT lists:

```sql
        ed.data_column AS data_column,
```

- [ ] **Step 4: Replace the type branch in `_aggregate_data_rows`**

In `backend/visualize/data.py`, replace:

```python
        dtype = dr["data_column"]
        if dtype == "int":
            value = dr["int_value"]
            value = int(value) if value is not None else None
        elif dtype == "float":
            value = dr["float_value"]
            value = float(value) if value is not None else None
        else:
            value = dr["str_value"]
        record[col] = value
```

with:

```python
        # Whichever column the unnest produced a value in. All three NULL is a
        # nodata result and stays None.
        if dr["int_value"] is not None:
            value = int(dr["int_value"])
        elif dr["float_value"] is not None:
            value = float(dr["float_value"])
        else:
            value = dr["str_value"]
        record[col] = value
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python manage.py test visualize -v 2`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add backend/visualize/data.py backend/visualize/tests/test_data.py
git commit -m "Read scalar value columns in visualize

unnest(NULL) yields no rows, so a scalar row would disappear from both
the request and explore payloads. Wraps each scalar in a 1-element array
so one lateral covers both row shapes, and drops the data_column
discriminator from both queries."
```

---

### Task 6: Drop the data_column discriminator

**Goal:** `data_column` is gone from the model, the database, and the tests, now that six typed columns make it redundant.

**Files:**
- Modify: `backend/analytics/models.py`
- Create: `backend/analytics/migrations/0028_extractdata_drop_data_column.py`
- Modify: `backend/analytics/tests/test_processing.py`, `backend/analytics/tests/test_merge.py`, `backend/visualize/tests/test_data.py`
- Modify: `backend/mcp_server/tests/factories.py:117` — passes `data_column="float"` to `ExtractData.objects.create()`, which becomes a `TypeError` once the field is gone

**Acceptance Criteria:**
- [ ] `grep -rn "data_column" backend/ --include=*.py` returns only migration files
- [ ] Migration 0028 applies cleanly
- [ ] `python manage.py makemigrations --check --dry-run` reports no pending changes
- [ ] Full suite passes

**Verify:** `python manage.py test -v 1` (the FULL suite, not just `analytics visualize`) → 697 tests, 11 failures, all from the documented baseline

**Steps:**

- [ ] **Step 1: Remove the field and rewrite the docstring**

In `backend/analytics/models.py`, delete the `data_column` line, and replace the "Two independent levels of NULL" paragraph of the `ExtractData` docstring with:

```python
    One row per (extract_task, name) -- see ExtractTask.resource_ids.

    A row populates exactly one side. Single-resource tasks use the scalar
    columns (int_value/float_value/str_value); grouped tasks use the array
    columns, position-aligned with resource_ids so index i is the result for
    resource_ids[i]. The unused side stays NULL, which in PostgreSQL costs
    only a null-bitmap bit.

    A NULL value means nodata: the extraction ran and found nothing there.
    It does NOT mean "still needs processing" -- that was the old meaning, and
    it is why nodata used to be stored as the string 'None'. Whether a task
    still needs work is a property of ExtractTask.status, not of this row. A
    row with every value column NULL is a complete record of a task that
    produced no data.
```

- [ ] **Step 2: Write the migration**

Create `backend/analytics/migrations/0028_extractdata_drop_data_column.py`:

```python
from django.db import migrations


class Migration(migrations.Migration):
    """Drop the data_column discriminator.

    Redundant now that each type has its own column on both the scalar and
    array side: the type is whichever column is non-NULL, and nothing needs
    the type of a NULL value -- every reader skips NULLs regardless.

    DROP COLUMN is catalog-only in PostgreSQL; it does not reclaim the space,
    which is immaterial here because reset_extract_data truncates the table
    outright.
    """

    dependencies = [
        ("analytics", "0027_extractdata_scalar_values"),
    ]

    operations = [
        migrations.RemoveField(model_name="extractdata", name="data_column"),
    ]
```

- [ ] **Step 3: Strip data_column from the tests**

Remove every `data_column=...` keyword argument and every `assertEqual(row.data_column, ...)` assertion across the three test files. Find them with:

Run: `grep -rn "data_column" backend/analytics/tests/ backend/visualize/tests/`

For `test_merge.py`'s `ExtractData.objects.create(...)` calls, drop only the `data_column=` argument and leave the `*_values=` arguments as they are — the merge reader now selects on those.

- [ ] **Step 4: Fix the mcp_server test factory**

`backend/mcp_server/tests/factories.py:117` builds ExtractData rows with `data_column="float"`. Drop that one keyword argument, leaving `float_values=[value]` intact:

```python
        ExtractData.objects.create(
            extract_task=task,
            dataset_id=self.dataset.id,
            name=name,
            float_values=[value],
        )
```

- [ ] **Step 5: Confirm nothing outside migrations references it**

Run: `grep -rn "data_column" backend/ --include=*.py | grep -v migrations`
Expected: no output.

- [ ] **Step 6: Apply and run the full suite**

Run: `python manage.py migrate analytics && python manage.py makemigrations --check --dry-run && python manage.py test -v 1`
Expected: migration OK, `No changes detected`, and **697 tests with 11 failures** — every one of them from the documented baseline list. `analytics visualize` alone is NOT sufficient here.

- [ ] **Step 7: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/0028_extractdata_drop_data_column.py backend/analytics/tests/ backend/visualize/tests/ backend/mcp_server/tests/factories.py
git commit -m "Drop the extract_data data_column discriminator

Redundant now that each type has its own scalar and array column: the
type is whichever is non-NULL, and no reader needs the type of a NULL.
Saves 4-6 bytes on every row."
```

---

### Task 7: Cutover command

**Goal:** A management command that discards all extract data and returns processed tasks to pending, partition by partition, so the transient bloat stays bounded.

**Files:**
- Create: `backend/analytics/management/commands/reset_extract_data.py`
- Create: `backend/analytics/tests/test_reset_extract_data.py`

**Acceptance Criteria:**
- [ ] Running without `--confirm` changes nothing and exits non-zero
- [ ] With `--confirm`, `extract_data` is empty and every task with `status <> 0` is left at `status=0` with `complete_time`, `attempts`, and `error` cleared
- [ ] Tasks already at `status=0` are not rewritten
- [ ] Each `extract_tasks` partition is updated in its own statement, with a `VACUUM` between
- [ ] `--dry-run` reports the per-partition row counts it would reset and changes nothing

**Verify:** `python manage.py test analytics.tests.test_reset_extract_data -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `backend/analytics/tests/test_reset_extract_data.py`:

```python
from io import StringIO

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import TransactionTestCase

from analytics.models import ExtractData, ExtractTask, ProcessingOption
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection


class ResetExtractDataTest(TransactionTestCase):
    """reset_extract_data: the cutover that discards derived extract results.

    TransactionTestCase rather than TestCase because the command issues
    TRUNCATE and VACUUM, neither of which behaves inside the wrapping
    transaction TestCase would hold open.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset, short_name="mean",
            function="rasterstats_default_mean", active=True,
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r0", path="r0.tif"
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        self.fm = FeatMap.objects.create(
            fc=fc, geom=Feature.objects.create(shape=Point(0, 0))
        )

    def _task(self, status):
        return ExtractTask.objects.create(
            resource_ids=[self.resource.id], dataset_id=self.dataset.id,
            fm=self.fm, po=self.po, status=status, attempts=2,
        )

    def test_refuses_without_confirm(self):
        task = self._task(status=1)
        ExtractData.objects.create(
            extract_task_id=task.id, dataset_id=self.dataset.id,
            name="mean", float_value=1.0,
        )

        with self.assertRaises(SystemExit):
            call_command("reset_extract_data", stdout=StringIO())

        self.assertEqual(ExtractData.objects.count(), 1)
        task.refresh_from_db()
        self.assertEqual(task.status, 1)

    def test_dry_run_changes_nothing(self):
        task = self._task(status=1)
        call_command("reset_extract_data", "--dry-run", stdout=StringIO())
        task.refresh_from_db()
        self.assertEqual(task.status, 1)

    def test_confirm_truncates_and_resets(self):
        done = self._task(status=1)
        done.complete_time = "2026-09-01T00:00:00Z"
        done.error = "stale"
        done.save()
        pending = self._task(status=0)
        ExtractData.objects.create(
            extract_task_id=done.id, dataset_id=self.dataset.id,
            name="mean", float_value=1.0,
        )

        call_command("reset_extract_data", "--confirm", stdout=StringIO())

        self.assertEqual(ExtractData.objects.count(), 0)
        done.refresh_from_db()
        self.assertEqual(done.status, 0)
        self.assertIsNone(done.complete_time)
        self.assertIsNone(done.error)
        self.assertEqual(done.attempts, 0)
        pending.refresh_from_db()
        self.assertEqual(pending.status, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test analytics.tests.test_reset_extract_data -v 2`
Expected: FAIL — `CommandError: Unknown command: 'reset_extract_data'`.

- [ ] **Step 3: Write the command**

Create `backend/analytics/management/commands/reset_extract_data.py`:

```python
import sys
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import connection


logger = getLogger(__name__)

# Which extract_tasks partitions exist. extract_tasks is LIST partitioned on
# dataset_id, so resetting per-partition keeps each statement's dead-tuple
# footprint to one partition instead of rewriting 347M rows in one shot.
_PARTITIONS_SQL = """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relname LIKE 'extract_tasks_ds%'
    ORDER BY c.relname
"""

_COUNT_SQL = "SELECT count(*) FROM {table} WHERE status <> 0"

# complete_time, attempts and error are cleared alongside status so a reset
# task is indistinguishable from one that has never run. Leaving a stale
# complete_time behind would keep it in stats/builder.py's completions chart
# while it sits pending.
_RESET_SQL = """
    UPDATE {table}
    SET status = 0, complete_time = NULL, attempts = 0, error = NULL
    WHERE status <> 0
"""


class Command(BaseCommand):
    help = (
        "Discard every extract_data row and return processed extract tasks to "
        "pending, so they are re-extracted into the current schema."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually do it. Without this the command refuses.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be reset, per partition, and change nothing.",
        )

    def handle(self, *_args, **options):
        if not options["dry_run"] and not options["confirm"]:
            self.stderr.write(
                self.style.ERROR(
                    "Refusing to run without --confirm. This TRUNCATEs extract_data "
                    "and resets every processed extract task to pending; the data is "
                    "regenerable but re-extracting it costs days of fleet capacity."
                )
            )
            sys.exit(1)

        # VACUUM cannot run inside a transaction block.
        connection.set_autocommit(True)

        with connection.cursor() as cursor:
            cursor.execute(_PARTITIONS_SQL)
            partitions = [r[0] for r in cursor.fetchall()]

        if options["dry_run"]:
            total = 0
            with connection.cursor() as cursor:
                for table in partitions:
                    cursor.execute(_COUNT_SQL.format(table=table))
                    n = cursor.fetchone()[0]
                    total += n
                    if n:
                        self.stdout.write(f"{table}: would reset {n:,} tasks")
            self.stdout.write(
                self.style.WARNING(f"dry run: {total:,} tasks across {len(partitions)} partitions")
            )
            return

        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE extract_data")
        self.stdout.write(self.style.SUCCESS("extract_data truncated"))

        total = 0
        for table in partitions:
            with connection.cursor() as cursor:
                cursor.execute(_RESET_SQL.format(table=table))
                n = cursor.rowcount
                total += n
                # Between partitions, not at the end: the point is to keep the
                # dead tuples from one partition's rewrite from accumulating
                # across all 57 of them at once.
                cursor.execute(f"VACUUM {table}")
            if n:
                self.stdout.write(f"{table}: reset {n:,} tasks, vacuumed")
            logger.info("reset_extract_data: %s reset %d tasks", table, n)

        self.stdout.write(
            self.style.SUCCESS(f"reset {total:,} tasks across {len(partitions)} partitions")
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python manage.py test analytics.tests.test_reset_extract_data -v 2`
Expected: OK, 3 tests.

- [ ] **Step 5: Run the whole suite**

Run: `python manage.py test analytics visualize -v 2`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/management/commands/reset_extract_data.py backend/analytics/tests/test_reset_extract_data.py
git commit -m "Add reset_extract_data cutover command

TRUNCATEs extract_data and returns processed tasks to pending, one
extract_tasks partition at a time with a VACUUM between so the dead
tuples from 347M rewritten rows do not accumulate across all 57
partitions at once. Refuses without --confirm."
```

---

## Execution order and production cutover

Tasks 1 → 2 → 3 → 4 → 5 → 6 → 7, each depending on the one before. Tasks 2 and 3 in particular must not be reordered: making nodata NULL before completeness moves off array contents would leave every nodata task retrying forever.

Once merged and deployed, the production cutover is manual:

```bash
djm reset_extract_data --dry-run     # confirm the partition counts look right
djm reset_extract_data --confirm
```

Expect ~347M tasks reset and roughly ten days of re-processing at the measured 1.42M tasks/hr. `extract_data` returns ~115 GB to the volume immediately; the reset transiently consumes ~80 GB of that in dead heap and pending-index growth before autovacuum catches up.
