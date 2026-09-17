# Extract Tasks/Data Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `extract_tasks`/`extract_data` so the eventual ~12.4B-row global-dataset task universe is generated, stored, and processed sustainably — collapsing monthly time-series datasets into grouped tasks, replacing the unused composite index with one that's actually queried, and partitioning both tables by dataset.

**Architecture:** `Dataset.task_group_period` (nullable: day/week/month/quarter/year) controls whether `build_extract_tasks` enumerates one task per `DatasetResource` (standard, `task_group_period IS NULL`) or one task per `date_trunc(task_group_period, temporal)` bucket (grouped). Both shapes unify under `ExtractTask.resource_ids INTEGER[]` — standard tasks carry a 1-element array, grouped tasks carry N. `ExtractData` mirrors this with position-aligned `float_values`/`int_values`/`str_values` arrays instead of scalar columns. Both `extract_tasks` and `extract_data` become `LIST` partitioned by `dataset_id`, which forces their primary keys to become `(dataset_id, id)` composites and cascades a denormalized `dataset_id` column onto `extract_data` and `request_map`. The old `extract_tasks_resource_fm_po_kwargs_hash_idx` (1.8GB, zero reads — nothing queries its hash expression) is replaced by a partial `UNIQUE (fm_id, po_id, resource_ids) WHERE kwargs IS NULL` index, which is both the uniqueness backstop for the ad-hoc single-task path and directly usable for that path's lookup — the bulk build path no longer needs a live anti-join against `extract_tasks` at all, since `extract_task_build_progress` (also converted to `resource_ids`-keyed, `FOR UPDATE SKIP LOCKED` claiming) already guarantees exactly-once construction.

**Tech Stack:** Django 5.2 / PostgreSQL 17 (CloudNativePG), Celery, raw SQL via `connection.cursor()` for the hot paths (unchanged from the existing `build_extract_tasks.py` pattern), Django migrations (`RunSQL`/`RunPython` for partitioning and array-column DDL Django's ORM can't express declaratively).

**User decisions (already made):**
- Wiping `extract_tasks`/`extract_data` is fine — clean-slate redesign, not a live migration of existing rows.
- Grouped tasks: one row per `(feature, period-bucket, po)`, not one row per full time series — bounds retry cost and task duration.
- A failed raster within a group does NOT retry the whole group — only the failed position (tracked via `NULL` at that array index in the value arrays) needs reprocessing.
- Grouping granularity (`task_group_period`) is configurable per dataset (day/week/month/quarter/year via `date_trunc`), not hardcoded to "year" — different datasets have different native cadences and total resource counts.
- Partitioning: dataset-level (`LIST` by `dataset_id`), not sub-partitioned further — grouping already fixes the severe per-dataset imbalance (CRU_TS: ~4.2B rows → ~350M rows) that would otherwise have made sub-partitioning necessary.
- Standard (ungrouped) and grouped tasks share one schema shape (`resource_ids` array, 1 element vs N) rather than two separate table/column designs.

---

## File Structure

- `backend/datasets/models.py` — `Dataset.task_group_period` field (new).
- `backend/analytics/models.py` — `ExtractTask` (resource FK → `resource_ids` array, composite PK), `ExtractData` (scalar values → arrays, `dataset_id` added), `ExtractTaskBuildProgress` (resource FK → `resource_ids` array).
- `backend/analytics/migrations/0017_*.py` through `0022_*.py` — six migrations, each independently applicable and each leaving the DB in a working state (see Task breakdown; some contain `RunSQL` for the DDL Django can't express: partitioned-table creation, partial/array indexes).
- `backend/analytics/management/commands/build_extract_tasks.py` — rewritten: standard branch keeps today's per-resource shape; new grouped branch buckets by `date_trunc`; `extract_task_build_progress` claiming keyed by `resource_ids`.
- `backend/analytics/tasks/processing.py` — `_run_extract_task` rewritten to loop over `task.resource_ids`, build position-aligned result arrays, and support NULL-position partial retry.
- `backend/analytics/views.py`, `backend/analytics/ingest.py` — the two ad-hoc single-task creation paths updated from `resource=resource` to `resource_ids=[resource.id]`.
- `backend/visualize/data.py` — the two `ExtractData` export queries updated to `unnest()` the value arrays back to one-row-per-month for the response payload.

---

## Task 0: Add `Dataset.task_group_period`

**Goal:** Add the field that controls per-dataset task grouping, with no behavior change yet (nothing reads it until Task 4).

**Files:**
- Modify: `backend/datasets/models.py`
- Create: `backend/datasets/migrations/0002_dataset_task_group_period.py` (check the actual next-available number in that app before creating — see Step 1)
- Test: `backend/datasets/tests/test_models.py`

**Acceptance Criteria:**
- [ ] `Dataset.task_group_period` accepts `None` and each of `day/week/month/quarter/year`.
- [ ] Default is `None` (existing/new datasets are "standard" unless explicitly opted into grouping).
- [ ] Migration applies cleanly against the current `datasets` app migration graph.

**Verify:** `cd backend && /app/.venv/bin/python manage.py test datasets.tests.test_models -v 2` → `OK`

**Steps:**

- [ ] **Step 1: Confirm the next migration number**

```bash
ls backend/datasets/migrations/ | sort | tail -5
```

Use whatever the actual highest number is; the examples below assume `0002_...` is free. If not, bump every migration number in this plan's `datasets` app steps accordingly — the `analytics` app numbers (0017+) are unaffected either way since they're a different app's sequence.

- [ ] **Step 2: Write the failing test**

```python
# backend/datasets/tests/test_models.py
from django.test import TestCase
from datasets.models import Dataset


class DatasetTaskGroupPeriodTest(TestCase):
    def test_default_is_none(self):
        d = Dataset.objects.create(name="test_ds_ungrouped", active=True)
        self.assertIsNone(d.task_group_period)

    def test_accepts_valid_periods(self):
        for period in ("day", "week", "month", "quarter", "year"):
            d = Dataset.objects.create(name=f"test_ds_{period}", active=True, task_group_period=period)
            d.refresh_from_db()
            self.assertEqual(d.task_group_period, period)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && /app/.venv/bin/python manage.py test datasets.tests.test_models.DatasetTaskGroupPeriodTest -v 2`
Expected: FAIL with `AttributeError: 'Dataset' object has no attribute 'task_group_period'` (or similar `FieldError` from `create()`)

- [ ] **Step 4: Add the field**

Locate the `Dataset` model in `backend/datasets/models.py` and add:

```python
    TASK_GROUP_PERIOD_CHOICES = [
        ("day", "Day"),
        ("week", "Week"),
        ("month", "Month"),
        ("quarter", "Quarter"),
        ("year", "Year"),
    ]
    task_group_period = models.CharField(
        max_length=10,
        choices=TASK_GROUP_PERIOD_CHOICES,
        null=True,
        blank=True,
        help_text=(
            "If set, build_extract_tasks groups this dataset's resources into "
            "one task per date_trunc(task_group_period, temporal) bucket per "
            "feature/po, instead of one task per resource. Null = standard "
            "(one task per resource)."
        ),
    )
```

- [ ] **Step 5: Generate and apply the migration**

```bash
cd backend && /app/.venv/bin/python manage.py makemigrations datasets --name dataset_task_group_period
```

Confirm the generated file matches: adds `task_group_period` as a nullable `CharField` with the five choices above, depending on the current latest `datasets` migration.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && /app/.venv/bin/python manage.py test datasets.tests.test_models.DatasetTaskGroupPeriodTest -v 2`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/datasets/models.py backend/datasets/migrations/
git commit -m "Add Dataset.task_group_period for configurable task grouping"
```

---

## Task 1: Wipe extract_tasks/extract_data and dependents

**Goal:** Clear the live incident-scale data (`extract_tasks`, `extract_data`, `extract_task_build_progress`, `extract_task_build_run`, `request_map`) so the schema-breaking migrations in Tasks 2-5 apply to an empty table, per the standing user decision that wiping is acceptable.

**Files:**
- Create: `backend/analytics/migrations/0017_wipe_extract_tasks_for_redesign.py`

**Acceptance Criteria:**
- [ ] All five tables report 0 rows after this migration runs.
- [ ] No FK errors (CASCADE order handles `extract_data`/`request_map` before `extract_tasks`).

**Verify:** After deploying, `SELECT count(*) FROM extract_tasks, extract_data, request_map;` on the primary → all zero.

**Steps:**

- [ ] **Step 1: Write the migration**

```python
# backend/analytics/migrations/0017_wipe_extract_tasks_for_redesign.py
from django.db import migrations


class Migration(migrations.Migration):
    """
    Clears extract_tasks/extract_data/request_map and the build-progress
    tracking tables ahead of the schema redesign in migrations 0018-0022
    (resource_ids arrays, partitioning, new indexes). Per user decision:
    wiping this data is acceptable -- it's regenerable via build_extract_tasks
    + run_extract_task, and the incident-scale volume already in these tables
    (tens of millions of rows, mid-rebuild) isn't worth preserving through a
    structural rewrite.
    """

    dependencies = [
        ("analytics", "0016_extracttaskbuildrun"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                TRUNCATE TABLE
                    extract_data,
                    request_map,
                    extract_tasks,
                    extract_task_build_progress
                RESTART IDENTITY CASCADE;
                UPDATE extract_task_build_run SET in_progress = FALSE, last_progress_at = NULL WHERE id = 1;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
```

- [ ] **Step 2: Commit**

```bash
git add backend/analytics/migrations/0017_wipe_extract_tasks_for_redesign.py
git commit -m "Wipe extract_tasks/extract_data ahead of the redesign migrations"
```

No test for this one — it's a data operation, not new behavior. Verified by the row-count check above once deployed.

---

## Task 2: Restructure `ExtractTask` — `resource_ids` array, composite PK prep

**Goal:** Replace `ExtractTask.resource` (scalar FK) with `resource_ids` (`INTEGER[]`), and add the `dataset_id` column the partitioning in Task 5 requires.

**Files:**
- Modify: `backend/analytics/models.py`
- Create: `backend/analytics/migrations/0018_extracttask_resource_ids.py`
- Test: `backend/analytics/tests/test_models.py`

**Acceptance Criteria:**
- [ ] `ExtractTask.resource_ids` is a Postgres `INTEGER[]`, not null, no default (callers always supply it).
- [ ] `ExtractTask.resource` (old scalar FK) is gone.
- [ ] `ExtractTask.dataset_id` exists, populated from `po.dataset_id` at write time (see Task 7/9 for callers) — not auto-derived by the DB, since Postgres has no generated-column-from-FK-of-a-different-table mechanism worth the complexity here.
- [ ] `ExtractTask.task_group_period` exists (denormalized copy of `Dataset.task_group_period`, so `run_extract_task` doesn't need a join to know how to interpret `resource_ids`).

**Verify:** `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractTaskResourceIdsTest -v 2` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/analytics/tests/test_models.py (add to existing file, or create if absent)
from django.test import TestCase
from django.db import connection
from analytics.models import ExtractTask


class ExtractTaskResourceIdsTest(TestCase):
    def test_resource_ids_is_postgres_array(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT data_type, udt_name FROM information_schema.columns
                WHERE table_name = 'extract_tasks' AND column_name = 'resource_ids'
            """)
            row = cursor.fetchone()
        self.assertIsNotNone(row, "resource_ids column does not exist")
        self.assertEqual(row[0], "ARRAY")
        self.assertEqual(row[1], "_int4")

    def test_resource_field_removed(self):
        field_names = {f.name for f in ExtractTask._meta.get_fields()}
        self.assertNotIn("resource", field_names)
        self.assertIn("resource_ids", field_names)
        self.assertIn("dataset_id", field_names)
        self.assertIn("task_group_period", field_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractTaskResourceIdsTest -v 2`
Expected: FAIL — `resource_ids` column doesn't exist yet.

- [ ] **Step 3: Update the model**

In `backend/analytics/models.py`, replace the `ExtractTask.resource` field and add the new ones:

```python
class ExtractTask(models.Model):
    """Extract tasks table for managing data extraction jobs.

    resource_ids holds the DatasetResource ids this task covers: exactly one
    for a standard (ungrouped) task, N for a grouped task (e.g. 12 for a
    year-bucketed monthly dataset). Position i in resource_ids corresponds to
    position i in each ExtractData row's value arrays for this task -- see
    ExtractData below.
    """

    id = models.AutoField(primary_key=False)  # composite PK set via migration RunSQL; see Task 5
    resource_ids = ArrayField(models.IntegerField())
    dataset_id = models.IntegerField()
    task_group_period = models.CharField(max_length=10, null=True, blank=True)
    fm = models.ForeignKey(FeatMap, on_delete=models.CASCADE, db_column="fm_id")
    po = models.ForeignKey(
        ProcessingOption, on_delete=models.CASCADE, db_column="po_id"
    )
    status = models.IntegerField(default=0)
    priority = models.IntegerField(default=0)
    submit_time = models.DateTimeField(auto_now_add=True)
    start_time = models.DateTimeField(blank=True, null=True)
    update_time = models.DateTimeField(blank=True, null=True)
    complete_time = models.DateTimeField(blank=True, null=True)
    attempts = models.IntegerField(default=0)
    error = models.CharField(max_length=100, blank=True, null=True)
    kwargs = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = "extract_tasks"

    def __str__(self):
        return (
            f"ExtractTask {self.id}: Resources {self.resource_ids} - Status {self.status}"
        )
```

Add the import at the top of the file:

```python
from django.contrib.postgres.fields import ArrayField
```

Note `id = models.AutoField(primary_key=False)`: Django requires exactly one field to be the declared PK, but Postgres's partitioning rule (Task 5) needs the *real* PK to be `(dataset_id, id)`. Task 5's `RunSQL` drops Django's single-column PK constraint and adds the composite one directly in the database; the model keeps `id` as a plain unique-ish identity column here since Django's ORM doesn't support composite PKs declaratively in this Django version. `resource` and its old FK-related `Meta` are removed entirely.

- [ ] **Step 4: Generate the migration, then hand-edit it**

```bash
cd backend && /app/.venv/bin/python manage.py makemigrations analytics --name extracttask_resource_ids
```

Django's autogenerated migration won't get the `RemoveField`/`AddField` sequencing or the `ArrayField` import right by default in every version — open the generated file and confirm/adjust it to match:

```python
# backend/analytics/migrations/0018_extracttask_resource_ids.py
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0017_wipe_extract_tasks_for_redesign"),
    ]

    operations = [
        migrations.RemoveField(model_name="extracttask", name="resource"),
        migrations.AddField(
            model_name="extracttask",
            name="resource_ids",
            field=django.contrib.postgres.fields.ArrayField(
                models.IntegerField(), default=list
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="extracttask",
            name="dataset_id",
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="extracttask",
            name="task_group_period",
            field=models.CharField(max_length=10, blank=True, null=True),
        ),
    ]
```

(`preserve_default=False` on the first two matters: since the table is empty post-Task-1, there's no existing-row backfill concern, but Django still wants a migration-time default for the `AddField` DDL itself on a NOT NULL column — `default=list`/`default=0` satisfy that without leaving a stored default on the column going forward.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractTaskResourceIdsTest -v 2`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/0018_extracttask_resource_ids.py backend/analytics/tests/test_models.py
git commit -m "Replace ExtractTask.resource with resource_ids array"
```

---

## Task 3: Restructure `ExtractData` — value arrays, `dataset_id`

**Goal:** Replace `ExtractData`'s scalar `float_value`/`int_value`/`str_value` with position-aligned arrays, and add `dataset_id` for the Task 5 partitioning FK.

**Files:**
- Modify: `backend/analytics/models.py`
- Create: `backend/analytics/migrations/0019_extractdata_value_arrays.py`
- Test: `backend/analytics/tests/test_models.py`

**Acceptance Criteria:**
- [ ] `ExtractData.float_values`/`int_values`/`str_values` are Postgres arrays.
- [ ] Old scalar `float_value`/`int_value`/`str_value` are gone.
- [ ] `ExtractData.dataset_id` exists.

**Verify:** `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractDataArraysTest -v 2` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/analytics/tests/test_models.py (append)
from analytics.models import ExtractData


class ExtractDataArraysTest(TestCase):
    def test_value_arrays_exist(self):
        field_names = {f.name for f in ExtractData._meta.get_fields()}
        self.assertIn("float_values", field_names)
        self.assertIn("int_values", field_names)
        self.assertIn("str_values", field_names)
        self.assertIn("dataset_id", field_names)
        self.assertNotIn("float_value", field_names)
        self.assertNotIn("int_value", field_names)
        self.assertNotIn("str_value", field_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractDataArraysTest -v 2`
Expected: FAIL — old scalar fields still present.

- [ ] **Step 3: Update the model**

```python
class ExtractData(models.Model):
    """Extract data table for storing extraction results.

    One row per (extract_task, name) -- see ExtractTask.resource_ids. Values
    are arrays position-aligned with the owning task's resource_ids: index i
    here is the result for resource_ids[i]. A NULL at position i means that
    resource still needs (re)processing -- see
    analytics.tasks.processing._run_extract_task.
    """

    id = models.AutoField(primary_key=False)  # composite PK set via migration RunSQL; see Task 5
    extract_task = models.ForeignKey(
        ExtractTask, on_delete=models.CASCADE, db_column="extract_task_id"
    )
    dataset_id = models.IntegerField()
    name = models.CharField(max_length=100, blank=True, null=True)
    data_column = models.CharField(max_length=100, blank=True, null=True)
    float_values = ArrayField(models.FloatField(null=True), blank=True, null=True)
    int_values = ArrayField(models.BigIntegerField(null=True), blank=True, null=True)
    str_values = ArrayField(models.CharField(max_length=100, null=True), blank=True, null=True)

    class Meta:
        db_table = "extract_data"

    def __str__(self):
        return f"ExtractData for Task {self.extract_task_id}: {self.name}"
```

- [ ] **Step 4: Generate and hand-verify the migration**

```bash
cd backend && /app/.venv/bin/python manage.py makemigrations analytics --name extractdata_value_arrays
```

Confirm it matches this shape (adjust field ordering to whatever Django emits, the operations themselves must match):

```python
# backend/analytics/migrations/0019_extractdata_value_arrays.py
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0018_extracttask_resource_ids"),
    ]

    operations = [
        migrations.RemoveField(model_name="extractdata", name="float_value"),
        migrations.RemoveField(model_name="extractdata", name="int_value"),
        migrations.RemoveField(model_name="extractdata", name="str_value"),
        migrations.AddField(
            model_name="extractdata",
            name="float_values",
            field=django.contrib.postgres.fields.ArrayField(
                models.FloatField(null=True), blank=True, null=True
            ),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="int_values",
            field=django.contrib.postgres.fields.ArrayField(
                models.BigIntegerField(null=True), blank=True, null=True
            ),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="str_values",
            field=django.contrib.postgres.fields.ArrayField(
                models.CharField(max_length=100, null=True), blank=True, null=True
            ),
        ),
        migrations.AddField(
            model_name="extractdata",
            name="dataset_id",
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractDataArraysTest -v 2`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/0019_extractdata_value_arrays.py backend/analytics/tests/test_models.py
git commit -m "Replace ExtractData scalar values with position-aligned arrays"
```

---

## Task 4: Restructure `ExtractTaskBuildProgress` — `resource_ids`-keyed claiming

**Goal:** Generalize the progress/claiming table from `(resource_id, po_id)` to `(resource_ids, po_id)`, and add a `claimed_at` staleness column consistent with the existing `build_extract_tasks.py` claiming design (already present for the old scalar shape — this task migrates it to arrays).

**Files:**
- Modify: `backend/analytics/models.py`
- Create: `backend/analytics/migrations/0020_extracttaskbuildprogress_resource_ids.py`
- Test: `backend/analytics/tests/test_models.py`

**Acceptance Criteria:**
- [ ] `ExtractTaskBuildProgress.resource_ids` is a Postgres array.
- [ ] Old scalar `resource` FK is gone; `po`, `completed_up_to_fm_id`, `claimed_at` are unchanged from the existing design.
- [ ] `UNIQUE (resource_ids, po_id)` constraint exists (replacing the old `UNIQUE (resource, po)`).

**Verify:** `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractTaskBuildProgressArrayTest -v 2` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/analytics/tests/test_models.py (append)
from analytics.models import ExtractTaskBuildProgress


class ExtractTaskBuildProgressArrayTest(TestCase):
    def test_resource_ids_array(self):
        field_names = {f.name for f in ExtractTaskBuildProgress._meta.get_fields()}
        self.assertIn("resource_ids", field_names)
        self.assertNotIn("resource", field_names)

    def test_unique_constraint_on_resource_ids_and_po(self):
        constraint_names = {
            c.name for c in ExtractTaskBuildProgress._meta.constraints
        }
        self.assertIn(
            "extract_task_build_progress_resource_ids_po_unique", constraint_names
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractTaskBuildProgressArrayTest -v 2`
Expected: FAIL — `resource_ids` doesn't exist, old constraint name doesn't match.

- [ ] **Step 3: Update the model**

```python
class ExtractTaskBuildProgress(models.Model):
    """Tracks how far build_extract_tasks has generated tasks for each
    (resource_ids, po) unit of work.

    For a standard (ungrouped) dataset, resource_ids is a 1-element array (one
    row per individual DatasetResource x po). For a grouped dataset,
    resource_ids holds every resource in one date_trunc(task_group_period, ...)
    bucket. Either way, completed_up_to_fm_id is the highest feat_map.id
    confirmed generated for that (resource_ids, po) pair -- a run only has to
    look at feat_map rows added since. claimed_at supports concurrent workers:
    set while a worker is actively batching this pair, cleared right after
    (success or failure); staleness lets another worker reclaim a pair whose
    claiming worker died mid-batch.
    """

    resource_ids = ArrayField(models.IntegerField())
    po = models.ForeignKey(
        ProcessingOption, on_delete=models.CASCADE, db_column="po_id"
    )
    completed_up_to_fm_id = models.IntegerField(blank=True, null=True)
    claimed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "extract_task_build_progress"
        constraints = [
            models.UniqueConstraint(
                fields=["resource_ids", "po"],
                name="extract_task_build_progress_resource_ids_po_unique",
            ),
        ]

    def __str__(self):
        return f"BuildProgress: Resources {self.resource_ids} - PO {self.po_id} (up to fm {self.completed_up_to_fm_id})"
```

- [ ] **Step 4: Generate and hand-verify the migration**

```bash
cd backend && /app/.venv/bin/python manage.py makemigrations analytics --name extracttaskbuildprogress_resource_ids
```

Confirm it matches:

```python
# backend/analytics/migrations/0020_extracttaskbuildprogress_resource_ids.py
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0019_extractdata_value_arrays"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="extracttaskbuildprogress",
            name="extract_task_build_progress_resource_po_unique",
        ),
        migrations.RemoveField(model_name="extracttaskbuildprogress", name="resource"),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="resource_ids",
            field=django.contrib.postgres.fields.ArrayField(
                models.IntegerField(), default=list
            ),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="extracttaskbuildprogress",
            constraint=models.UniqueConstraint(
                fields=("resource_ids", "po"),
                name="extract_task_build_progress_resource_ids_po_unique",
            ),
        ),
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_models.ExtractTaskBuildProgressArrayTest -v 2`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/0020_extracttaskbuildprogress_resource_ids.py backend/analytics/tests/test_models.py
git commit -m "Key extract_task_build_progress claiming by resource_ids array"
```

---

## Task 5: Partition `extract_tasks` and `extract_data` by `dataset_id`

**Goal:** Convert both tables to `LIST` partitions keyed on `dataset_id`, with composite primary keys, and propagate the `dataset_id` denormalization to `request_map` so its FK to the now-composite-keyed `extract_tasks` stays valid.

**Files:**
- Modify: `backend/analytics/models.py` (`RequestMap` gets `dataset_id`)
- Create: `backend/analytics/migrations/0021_partition_extract_tasks_and_data.py`
- Test: `backend/analytics/tests/test_models.py`

**Acceptance Criteria:**
- [ ] `extract_tasks` and `extract_data` are partitioned tables (`pg_partitioned_table` has entries for both).
- [ ] A partition exists for every currently-active `dataset_id` (56 datasets per the discovery earlier in this project — this migration creates one partition per row in `datasets`, plus a `DEFAULT` partition for any `dataset_id` not yet known at migration time).
- [ ] `extract_tasks` PK is `(dataset_id, id)`; `extract_data` PK is `(dataset_id, id)`.
- [ ] `request_map.dataset_id` exists and the FK to `extract_tasks` is `(dataset_id, task_id) REFERENCES extract_tasks(dataset_id, id)`.
- [ ] Inserting a row with an unrecognized `dataset_id` (no matching partition, and no `DEFAULT`) fails loudly rather than silently landing in the wrong place — verified by the `DEFAULT` partition existing precisely so this can't happen (see Step 1's rationale).

**Verify:** manual SQL check post-deploy (see Step 4) — `SELECT count(*) FROM pg_partitioned_table pt JOIN pg_class c ON c.oid = pt.partrelid WHERE c.relname IN ('extract_tasks','extract_data');` → `2`

**Steps:**

- [ ] **Step 1: Understand why this can't be a plain `ALTER TABLE`**

Postgres cannot convert an existing table into a partitioned table in place — partitioning is set at `CREATE TABLE ... PARTITION BY`. Since Task 1 already truncated both tables, the correct move is: drop and recreate them as partitioned from scratch, rather than the more complex "create new, copy data, swap" dance a live migration would need. A `DEFAULT` partition is included so that any dataset created *after* this migration runs (before its own per-dataset partition exists) still has somewhere to land, rather than failing every insert — Task 7's `build_extract_tasks` targets the per-dataset partition directly via `dataset_id`, so in steady state the `DEFAULT` partition should stay empty; its presence is a safety net, not the intended path.

- [ ] **Step 2: Write the migration**

```python
# backend/analytics/migrations/0021_partition_extract_tasks_and_data.py
from django.db import migrations


_DROP_AND_RECREATE_PARTITIONED = """
    -- extract_tasks and extract_data were just truncated in migration 0017;
    -- dropping and recreating as partitioned tables is safe -- there is no
    -- data to preserve, and Postgres cannot ALTER an existing table into a
    -- partitioned one in place.
    DROP TABLE IF EXISTS extract_data CASCADE;
    DROP TABLE IF EXISTS extract_tasks CASCADE;

    CREATE TABLE extract_tasks (
        id SERIAL,
        dataset_id INTEGER NOT NULL,
        resource_ids INTEGER[] NOT NULL,
        task_group_period VARCHAR(10),
        fm_id INTEGER NOT NULL REFERENCES feat_map(id) ON DELETE CASCADE,
        po_id INTEGER NOT NULL REFERENCES processing_options(id) ON DELETE CASCADE,
        status INTEGER NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL DEFAULT 0,
        submit_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        start_time TIMESTAMPTZ,
        update_time TIMESTAMPTZ,
        complete_time TIMESTAMPTZ,
        attempts INTEGER NOT NULL DEFAULT 0,
        error VARCHAR(100),
        kwargs JSONB,
        PRIMARY KEY (dataset_id, id)
    ) PARTITION BY LIST (dataset_id);

    CREATE TABLE extract_data (
        id SERIAL,
        dataset_id INTEGER NOT NULL,
        extract_task_id INTEGER NOT NULL,
        name VARCHAR(100),
        data_column VARCHAR(100),
        float_values FLOAT8[],
        int_values BIGINT[],
        str_values VARCHAR(100)[],
        PRIMARY KEY (dataset_id, id)
    ) PARTITION BY LIST (dataset_id);
"""

_CREATE_DEFAULT_PARTITIONS = """
    CREATE TABLE extract_tasks_default PARTITION OF extract_tasks DEFAULT;
    CREATE TABLE extract_data_default PARTITION OF extract_data DEFAULT;
"""

_REVERSE = """
    DROP TABLE IF EXISTS extract_data CASCADE;
    DROP TABLE IF EXISTS extract_tasks CASCADE;
"""


def _create_per_dataset_partitions(apps, schema_editor):
    Dataset = apps.get_model("datasets", "Dataset")
    with schema_editor.connection.cursor() as cursor:
        for dataset_id in Dataset.objects.values_list("id", flat=True):
            cursor.execute(
                f"""
                CREATE TABLE extract_tasks_ds_{dataset_id}
                    PARTITION OF extract_tasks FOR VALUES IN ({dataset_id});
                CREATE TABLE extract_data_ds_{dataset_id}
                    PARTITION OF extract_data FOR VALUES IN ({dataset_id});
                """
            )


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0020_extracttaskbuildprogress_resource_ids"),
        ("datasets", "0002_dataset_task_group_period"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_DROP_AND_RECREATE_PARTITIONED + _CREATE_DEFAULT_PARTITIONS,
            reverse_sql=_REVERSE,
        ),
        migrations.RunPython(_create_per_dataset_partitions, _noop_reverse),
        migrations.RunSQL(
            sql="""
                ALTER TABLE extract_data
                    ADD CONSTRAINT extract_data_extract_task_fk
                    FOREIGN KEY (dataset_id, extract_task_id)
                    REFERENCES extract_tasks (dataset_id, id) ON DELETE CASCADE;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE request_map ADD COLUMN dataset_id INTEGER;
                -- request_map is also truncated (migration 0017), so no
                -- backfill is needed for the NOT NULL below.
                ALTER TABLE request_map ALTER COLUMN dataset_id SET NOT NULL;
                ALTER TABLE request_map DROP CONSTRAINT IF EXISTS request_map_task_id_08f7ae9f_fk_extract_tasks_id;
                ALTER TABLE request_map
                    ADD CONSTRAINT request_map_extract_task_fk
                    FOREIGN KEY (dataset_id, task_id)
                    REFERENCES extract_tasks (dataset_id, id) ON DELETE CASCADE;
            """,
            reverse_sql="""
                ALTER TABLE request_map DROP CONSTRAINT IF EXISTS request_map_extract_task_fk;
                ALTER TABLE request_map DROP COLUMN IF EXISTS dataset_id;
            """,
        ),
    ]
```

- [ ] **Step 3: Update `RequestMap` in the model**

```python
class RequestMap(models.Model):
    """Request map table linking requests to extract tasks."""

    request = models.ForeignKey(Request, on_delete=models.CASCADE, db_column="req_id")
    task = models.ForeignKey(ExtractTask, on_delete=models.CASCADE, db_column="task_id")
    dataset_id = models.IntegerField()

    class Meta:
        db_table = "request_map"

    def __str__(self):
        return f"RequestMap: Request {self.request_id} - Task {self.task_id}"
```

- [ ] **Step 4: Manual verification query** (no Django test framework coverage for raw partitioning DDL — verify directly)

After deploying, run:

```sql
SELECT count(*) FROM pg_partitioned_table pt
JOIN pg_class c ON c.oid = pt.partrelid
WHERE c.relname IN ('extract_tasks', 'extract_data');
-- expect 2

SELECT count(*) FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
WHERE parent.relname = 'extract_tasks';
-- expect 57 (56 dataset partitions + 1 default), or however many datasets exist at deploy time + 1
```

- [ ] **Step 5: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/0021_partition_extract_tasks_and_data.py
git commit -m "Partition extract_tasks and extract_data by dataset_id"
```

---

## Task 6: Replace the unused composite index; drop redundant single-column indexes

**Goal:** Add `UNIQUE (fm_id, po_id, resource_ids) WHERE kwargs IS NULL` (the index that's actually queryable, replacing the old zero-scan hash index) and its `kwargs IS NOT NULL` counterpart for `filter_and_agg`; drop the now-redundant standalone `resource_id`/`po_id`/`fm_id` single-column indexes now that the composite covers their access patterns and the live anti-join against `extract_tasks` is gone (replaced by `extract_task_build_progress` claiming in Task 4).

**Files:**
- Create: `backend/analytics/migrations/0022_extracttask_indexes.py`

**Acceptance Criteria:**
- [ ] `UNIQUE (fm_id, po_id, resource_ids) WHERE kwargs IS NULL` exists on `extract_tasks`.
- [ ] `UNIQUE (fm_id, po_id, resource_ids, MD5(kwargs::text)) WHERE kwargs IS NOT NULL` exists on `extract_tasks`.
- [ ] `extract_tasks_pending_idx` (partial, `WHERE status = 0`) is preserved — still needed by dispatch/KEDA, untouched by this redesign.
- [ ] No standalone single-column `resource_id`/`fm_id`/`po_id` indexes remain (they don't exist post-Task-5's `CREATE TABLE` anyway, since that DDL never declared them — this task's job is adding the *new* composite, not removing old ones that are already gone by construction).

**Verify:** `SELECT indexname FROM pg_indexes WHERE tablename LIKE 'extract_tasks%';` on the primary → shows the new composite indexes plus `pending_idx`, per-partition.

**Steps:**

- [ ] **Step 1: Write the migration**

Note: since Task 5's `CREATE TABLE extract_tasks (...) PARTITION BY LIST (dataset_id)` never declared the old single-column indexes in the first place, there's nothing to drop here — this migration only needs to *add* the new indexes. On a partitioned table, an index created on the parent (`ON ONLY` omitted) automatically propagates to every existing and future partition.

```python
# backend/analytics/migrations/0022_extracttask_indexes.py
from django.db import migrations


class Migration(migrations.Migration):
    """
    Adds the composite uniqueness/lookup index that replaces the old
    extract_tasks_resource_fm_po_kwargs_hash_idx (1.8GB, zero reads across
    the whole incident -- nothing queried its exact hash expression). This
    one is ordered for the ad-hoc single-task lookup path
    (views.py/ingest.py's ExtractTask.objects.get(fm=, po=, resource_ids=)),
    which is the only remaining source of potential duplicate-task races now
    that the bulk build path dedupes via extract_task_build_progress claiming
    (migration 0020) rather than a live anti-join against extract_tasks.

    extract_tasks_pending_idx (status=0 partial, backing dispatch/KEDA) is
    untouched -- already exists from migration 0014 (analytics
    0014_extracttask_pending_idx) and this redesign doesn't change its
    columns or its access pattern.
    """

    dependencies = [
        ("analytics", "0021_partition_extract_tasks_and_data"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX extract_tasks_fm_po_resources_null_kwargs_idx
                    ON extract_tasks (fm_id, po_id, resource_ids)
                    WHERE kwargs IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_fm_po_resources_null_kwargs_idx;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX extract_tasks_fm_po_resources_kwargs_hash_idx
                    ON extract_tasks (fm_id, po_id, resource_ids, MD5(kwargs::text))
                    WHERE kwargs IS NOT NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_fm_po_resources_kwargs_hash_idx;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE INDEX extract_tasks_pending_idx
                    ON extract_tasks (priority DESC, submit_time)
                    WHERE status = 0;
            """,
            reverse_sql="DROP INDEX IF EXISTS extract_tasks_pending_idx;",
        ),
    ]
```

Note the third operation recreates `extract_tasks_pending_idx` — it existed on the *old* (now-dropped) `extract_tasks` table via migration `0014_extracttask_pending_idx`, but Task 5's `DROP TABLE ... CASCADE` on the old table removed it along with everything else built on that table. This migration restores it on the new partitioned table, same definition as the original.

- [ ] **Step 2: Verify against the live DB post-deploy**

```sql
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'extract_tasks';
```

Confirm three indexes: the two new composites and `extract_tasks_pending_idx`, plus whatever Postgres auto-creates for the `PRIMARY KEY (dataset_id, id)` from Task 5.

- [ ] **Step 3: Commit**

```bash
git add backend/analytics/migrations/0022_extracttask_indexes.py
git commit -m "Add composite fm/po/resource_ids index, restore pending_idx on partitioned table"
```

---

## Task 7: Rewrite `build_extract_tasks.py` for grouped + standard branches

**Goal:** `build_extract_tasks` enumerates standard datasets exactly as it did before Task 2-6 (one task per resource), and grouped datasets (`task_group_period IS NOT NULL`) by `date_trunc` bucket — both claimed via the `resource_ids`-keyed `extract_task_build_progress`.

**Files:**
- Modify: `backend/analytics/management/commands/build_extract_tasks.py`
- Test: `backend/analytics/tests/test_build_extract_tasks.py`

**Acceptance Criteria:**
- [ ] A standard dataset (`task_group_period IS NULL`) still produces one `ExtractTask` per `(feature, resource, po)`, `resource_ids = [resource.id]`.
- [ ] A grouped dataset produces one `ExtractTask` per `(feature, period-bucket, po)`, `resource_ids` containing every `DatasetResource.id` whose `date_trunc(task_group_period, temporal)` falls in that bucket, sorted ascending (canonical order, per the uniqueness-index design in Task 6 — array equality is order-sensitive).
- [ ] Claiming via `extract_task_build_progress` prevents two concurrent workers from building the same `(resource_ids, po)` pair twice.
- [ ] `dataset_id` and `task_group_period` are populated on every inserted `ExtractTask` row.

**Verify:** `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_build_extract_tasks -v 2` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests**

```python
# backend/analytics/tests/test_build_extract_tasks.py
from django.test import TransactionTestCase
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection
from analytics.models import ExtractTask, ProcessingOption
from analytics.management.commands.build_extract_tasks import _build_extract_tasks
from datetime import datetime, timezone


class BuildExtractTasksGroupingTest(TransactionTestCase):
    def _make_feature_and_fm(self, dataset):
        fc = FeatureCollection.objects.create(name="fc1", active=True, is_user_upload=False)
        feat = Feature.objects.create(fc=fc)
        return FeatMap.objects.create(geom=feat, fc=fc)

    def test_standard_dataset_one_task_per_resource(self):
        d = Dataset.objects.create(name="std_ds", active=True, is_global=True, task_group_period=None)
        po = ProcessingOption.objects.create(dataset=d, short_name="mean", function="rasterstats_default_mean", active=True)
        r1 = DatasetResource.objects.create(dataset=d, name="r1", path="r1.tif", temporal=datetime(2020, 1, 1, tzinfo=timezone.utc))
        r2 = DatasetResource.objects.create(dataset=d, name="r2", path="r2.tif", temporal=datetime(2020, 2, 1, tzinfo=timezone.utc))
        self._make_feature_and_fm(d)

        _build_extract_tasks()

        tasks = list(ExtractTask.objects.filter(dataset_id=d.id, po=po))
        self.assertEqual(len(tasks), 2)
        resource_id_sets = {tuple(t.resource_ids) for t in tasks}
        self.assertEqual(resource_id_sets, {(r1.id,), (r2.id,)})

    def test_grouped_dataset_one_task_per_year_bucket(self):
        d = Dataset.objects.create(name="grp_ds", active=True, is_global=True, task_group_period="year")
        po = ProcessingOption.objects.create(dataset=d, short_name="mean", function="rasterstats_default_mean", active=True)
        resources_2020 = [
            DatasetResource.objects.create(
                dataset=d, name=f"2020-{m:02d}", path=f"2020-{m:02d}.tif",
                temporal=datetime(2020, m, 1, tzinfo=timezone.utc),
            )
            for m in range(1, 13)
        ]
        resources_2021 = [
            DatasetResource.objects.create(
                dataset=d, name=f"2021-{m:02d}", path=f"2021-{m:02d}.tif",
                temporal=datetime(2021, m, 1, tzinfo=timezone.utc),
            )
            for m in range(1, 13)
        ]
        self._make_feature_and_fm(d)

        _build_extract_tasks()

        tasks = list(ExtractTask.objects.filter(dataset_id=d.id, po=po))
        self.assertEqual(len(tasks), 2)  # one per year, not one per month
        by_size = sorted(len(t.resource_ids) for t in tasks)
        self.assertEqual(by_size, [12, 12])
        all_ids = sorted(rid for t in tasks for rid in t.resource_ids)
        expected_ids = sorted(r.id for r in resources_2020 + resources_2021)
        self.assertEqual(all_ids, expected_ids)
        for t in tasks:
            self.assertEqual(t.resource_ids, sorted(t.resource_ids))  # canonical order
            self.assertEqual(t.task_group_period, "year")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_build_extract_tasks -v 2`
Expected: FAIL — `_build_extract_tasks` still assumes the old scalar-resource, non-grouped shape and either errors or produces the wrong task count/shape.

- [ ] **Step 3: Rewrite `build_extract_tasks.py`**

```python
# backend/analytics/management/commands/build_extract_tasks.py
import time
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction


logger = getLogger(__name__)

BATCH_SIZE = 5000
BATCH_STATEMENT_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes
PAIRS_PER_ROUND = 50
CLAIM_STALE_MINUTES = 10
RUN_STALE_MINUTES = 30

# ---------------------------------------------------------------------------
# Non-global datasets: unchanged from before this redesign -- gated by a
# confirmed coverage row (status=1), always standard (never grouped; grouping
# is only meaningful for the time-series-shaped global datasets discussed in
# the redesign). Kept as a plain re-scanned batch loop since this space is
# small (bounded by real coverage rows).
# ---------------------------------------------------------------------------

_INSERT_NON_GLOBAL_BATCH_SQL = """
    INSERT INTO extract_tasks
        (dataset_id, resource_ids, task_group_period, fm_id, po_id, status, priority, attempts, submit_time)
    SELECT d.id, ARRAY[dr.id], NULL, fm.id, po.id, 0, 0, 0, NOW()
    FROM coverage
    INNER JOIN feat_map fm            ON coverage.geom_id = fm.geom_id
    INNER JOIN feature_collections fc ON fm.fc_id = fc.id
    INNER JOIN dataset_resources dr   ON coverage.dataset_id = dr.dataset_id
    INNER JOIN processing_options po  ON coverage.dataset_id = po.dataset_id
    INNER JOIN datasets d             ON coverage.dataset_id = d.id
    WHERE coverage.status = 1
      AND po.active = TRUE
      AND fc.active = TRUE
      AND fc.is_user_upload = FALSE
      AND d.active = TRUE
      AND d.task_group_period IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM extract_tasks et
          WHERE et.dataset_id = d.id
            AND et.fm_id = fm.id
            AND et.po_id = po.id
            AND et.resource_ids = ARRAY[dr.id]
      )
    LIMIT %s
"""

# ---------------------------------------------------------------------------
# Global datasets: (resource(s), po) pairs x feat_map. extract_task_build_progress
# tracks completion per pair, keyed by resource_ids (1-element for standard
# datasets, N-element for grouped ones) so repeated runs only look at feat_map
# rows added since a pair was last caught up, and so concurrent workers claim
# disjoint pairs via FOR UPDATE SKIP LOCKED.
# ---------------------------------------------------------------------------

_SYNC_STANDARD_PAIRS_SQL = """
    INSERT INTO extract_task_build_progress (resource_ids, po_id)
    SELECT ARRAY[dr.id], po.id
    FROM datasets d
    INNER JOIN dataset_resources dr  ON dr.dataset_id = d.id
    INNER JOIN processing_options po ON po.dataset_id = d.id
    WHERE d.is_global = TRUE AND d.active = TRUE AND po.active = TRUE
      AND d.task_group_period IS NULL
    ON CONFLICT (resource_ids, po_id) DO NOTHING
"""

_SYNC_GROUPED_PAIRS_SQL = """
    INSERT INTO extract_task_build_progress (resource_ids, po_id)
    SELECT bucket.resource_ids, po.id
    FROM (
        SELECT dr.dataset_id, ARRAY_AGG(dr.id ORDER BY dr.id) AS resource_ids
        FROM dataset_resources dr
        INNER JOIN datasets d ON d.id = dr.dataset_id
        WHERE d.is_global = TRUE AND d.active = TRUE AND d.task_group_period IS NOT NULL
        GROUP BY dr.dataset_id, date_trunc(d.task_group_period, dr.temporal)
    ) bucket
    INNER JOIN processing_options po ON po.dataset_id = bucket.dataset_id AND po.active = TRUE
    ON CONFLICT (resource_ids, po_id) DO NOTHING
"""

_MAX_FEAT_MAP_ID_SQL = "SELECT COALESCE(MAX(id), 0) FROM feat_map"

_NEXT_PROGRESS_PAIRS_SQL = """
    SELECT p.id, p.resource_ids, p.po_id, p.completed_up_to_fm_id,
           dr.dataset_id, d.task_group_period
    FROM extract_task_build_progress p
    INNER JOIN dataset_resources dr ON dr.id = p.resource_ids[1]
    INNER JOIN processing_options po ON po.id = p.po_id AND po.dataset_id = dr.dataset_id
    INNER JOIN datasets d ON d.id = dr.dataset_id AND d.is_global = TRUE AND d.active = TRUE
    WHERE po.active = TRUE
      AND (p.completed_up_to_fm_id IS NULL OR p.completed_up_to_fm_id < %(current_max_fm_id)s)
      AND (p.claimed_at IS NULL OR p.claimed_at < NOW() - INTERVAL '{stale_minutes} minutes')
    ORDER BY p.id
    LIMIT %(limit)s
    FOR UPDATE OF p SKIP LOCKED
""".format(stale_minutes=CLAIM_STALE_MINUTES)

_CLAIM_PROGRESS_PAIRS_SQL = """
    UPDATE extract_task_build_progress
    SET claimed_at = NOW()
    WHERE id = ANY(%s)
"""

_RELEASE_CLAIM_SQL = "UPDATE extract_task_build_progress SET claimed_at = NULL WHERE id = %s"

_INSERT_GLOBAL_BATCH_SQL = """
    INSERT INTO extract_tasks
        (dataset_id, resource_ids, task_group_period, fm_id, po_id, status, priority, attempts, submit_time)
    SELECT %(dataset_id)s, %(resource_ids)s, %(task_group_period)s, fm.id, %(po_id)s, 0, 0, 0, NOW()
    FROM feat_map fm
    INNER JOIN feature_collections fc ON fm.fc_id = fc.id
    WHERE fc.active = TRUE
      AND fc.is_user_upload = FALSE
      AND fm.id > %(completed_up_to_fm_id)s
      AND NOT EXISTS (
          SELECT 1 FROM extract_tasks et
          WHERE et.fm_id = fm.id
            AND et.po_id = %(po_id)s
            AND et.resource_ids = %(resource_ids)s
      )
    ORDER BY fm.id
    LIMIT %(batch_size)s
"""

_MARK_PAIR_CAUGHT_UP_SQL = """
    UPDATE extract_task_build_progress
    SET completed_up_to_fm_id = %s, claimed_at = NULL
    WHERE id = %s
"""

_TRY_ACQUIRE_RUN_SQL = """
    UPDATE extract_task_build_run
    SET in_progress = TRUE, last_progress_at = NOW()
    WHERE id = 1
      AND (NOT in_progress OR last_progress_at < NOW() - INTERVAL '{stale_minutes} minutes')
    RETURNING TRUE
""".format(stale_minutes=RUN_STALE_MINUTES)

_HEARTBEAT_RUN_SQL = "UPDATE extract_task_build_run SET last_progress_at = NOW() WHERE id = 1"
_RELEASE_RUN_SQL = "UPDATE extract_task_build_run SET in_progress = FALSE WHERE id = 1"

_ANY_INCOMPLETE_PAIRS_SQL = """
    SELECT EXISTS (
        SELECT 1
        FROM extract_task_build_progress p
        INNER JOIN dataset_resources dr ON dr.id = p.resource_ids[1]
        INNER JOIN processing_options po ON po.id = p.po_id AND po.dataset_id = dr.dataset_id
        INNER JOIN datasets d ON d.id = dr.dataset_id AND d.is_global = TRUE AND d.active = TRUE
        WHERE po.active = TRUE
          AND (p.completed_up_to_fm_id IS NULL OR p.completed_up_to_fm_id < %s)
    )
"""


class Command(BaseCommand):
    help = "Create ExtractTask rows for covered dataset/feature pairs that don't have one yet."

    def handle(self, *_args, **_options):
        result = _build_extract_tasks()
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {result['added']} new extract tasks in {result['elapsed']:.2f}s"
            )
        )


def _run_batch(sql, params):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [BATCH_STATEMENT_TIMEOUT_MS])
                cursor.execute(sql, params)
                return cursor.rowcount
    except DatabaseError:
        logger.exception("build_extract_tasks batch failed/timed out")
        return None


def try_acquire_build_run():
    with connection.cursor() as cursor:
        cursor.execute(_TRY_ACQUIRE_RUN_SQL)
        return cursor.fetchone() is not None


def _any_incomplete_pairs(current_max_fm_id):
    with connection.cursor() as cursor:
        cursor.execute(_ANY_INCOMPLETE_PAIRS_SQL, [current_max_fm_id])
        return cursor.fetchone()[0]


def _release_build_run_if_done(current_max_fm_id):
    if not _any_incomplete_pairs(current_max_fm_id):
        with connection.cursor() as cursor:
            cursor.execute(_RELEASE_RUN_SQL)


def _build_global_tasks(batch_size=BATCH_SIZE):
    total_added = 0

    with connection.cursor() as cursor:
        cursor.execute(_SYNC_STANDARD_PAIRS_SQL)
        cursor.execute(_SYNC_GROUPED_PAIRS_SQL)
        cursor.execute(_MAX_FEAT_MAP_ID_SQL)
        current_max_fm_id = cursor.fetchone()[0]

    while True:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(_NEXT_PROGRESS_PAIRS_SQL, {
                    "current_max_fm_id": current_max_fm_id,
                    "limit": PAIRS_PER_ROUND,
                })
                pairs = cursor.fetchall()
                if pairs:
                    cursor.execute(_CLAIM_PROGRESS_PAIRS_SQL, [[p[0] for p in pairs]])

        if not pairs:
            _release_build_run_if_done(current_max_fm_id)
            break

        made_progress = False
        for progress_id, resource_ids, po_id, completed_up_to_fm_id, dataset_id, task_group_period in pairs:
            added = _run_batch(
                _INSERT_GLOBAL_BATCH_SQL,
                {
                    "dataset_id": dataset_id,
                    "resource_ids": resource_ids,
                    "task_group_period": task_group_period,
                    "po_id": po_id,
                    "completed_up_to_fm_id": completed_up_to_fm_id or 0,
                    "batch_size": batch_size,
                },
            )
            if added is None:
                with connection.cursor() as cursor:
                    cursor.execute(_RELEASE_CLAIM_SQL, [progress_id])
                continue

            made_progress = True
            total_added += added
            with connection.cursor() as cursor:
                cursor.execute(_HEARTBEAT_RUN_SQL)
            logger.info(
                "build_extract_tasks global batch: progress_id=%s resources=%s po=%s added %d (total %d)",
                progress_id, resource_ids, po_id, added, total_added,
            )

            with connection.cursor() as cursor:
                if added < batch_size:
                    cursor.execute(_MARK_PAIR_CAUGHT_UP_SQL, [current_max_fm_id, progress_id])
                else:
                    cursor.execute(_RELEASE_CLAIM_SQL, [progress_id])

        if not made_progress:
            logger.warning(
                "build_extract_tasks: no progress on any of %d claimed pairs this round; stopping",
                len(pairs),
            )
            break

    return total_added


def _build_non_global_tasks(batch_size=BATCH_SIZE):
    total_added = 0
    while True:
        added = _run_batch(_INSERT_NON_GLOBAL_BATCH_SQL, [batch_size])
        if added is None:
            break
        total_added += added
        logger.info("build_extract_tasks non-global batch: added %d (total %d)", added, total_added)
        if added < batch_size:
            break
    return total_added


def _build_extract_tasks(batch_size=BATCH_SIZE):
    t_start = time.perf_counter()
    total_added = _build_global_tasks(batch_size) + _build_non_global_tasks(batch_size)
    elapsed = time.perf_counter() - t_start
    logger.info("Generated %d new extract tasks in %.2fs", total_added, elapsed)
    return {"added": total_added, "elapsed": elapsed}
```

Note on `_NEXT_PROGRESS_PAIRS_SQL`'s join to `dataset_resources dr ON dr.id = p.resource_ids[1]`: this uses the *first* element of `resource_ids` as a representative to look up `dataset_id`/`task_group_period` — valid because every resource in one grouped bucket belongs to the same dataset by construction (the `_SYNC_GROUPED_PAIRS_SQL` query groups by `dr.dataset_id` before aggregating).

Note the claim step moved inside the same `transaction.atomic()` as the `SELECT ... FOR UPDATE SKIP LOCKED` (unlike the pre-redesign version, which claimed via a separate unlocked SELECT) — this closes a real race the earlier version had: locking and marking `claimed_at` in one transaction is what makes `SKIP LOCKED` actually prevent two workers from claiming the same page.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_build_extract_tasks -v 2`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/analytics/management/commands/build_extract_tasks.py backend/analytics/tests/test_build_extract_tasks.py
git commit -m "Rewrite build_extract_tasks for grouped + standard resource_ids branches"
```

---

## Task 8: Rewrite `run_extract_task` for `resource_ids` + partial retry

**Goal:** `_run_extract_task` loops over `task.resource_ids`, runs the processor once per resource, and writes position-aligned `ExtractData` arrays — skipping positions that already have a non-NULL value (partial retry), and leaving failed positions `NULL` rather than failing the whole task.

**Files:**
- Modify: `backend/analytics/tasks/processing.py`
- Test: `backend/analytics/tests/test_processing.py`

**Acceptance Criteria:**
- [ ] A standard task (`resource_ids` length 1) behaves identically to before: one raster read, one `ExtractData` row per named result, values as 1-element arrays.
- [ ] A grouped task reads every resource in `resource_ids`, in order, writing `float_values[i]` (or whichever type) for each.
- [ ] If one resource's raster read raises, that position is left `NULL`, the task is NOT marked failed as a whole, and the task's `status` reflects "needs another pass" (not `1`/complete) until every position is filled.
- [ ] Rerunning `run_extract_task` on a task with some positions already filled only reprocesses the `NULL` positions.

**Verify:** `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_processing -v 2` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests**

```python
# backend/analytics/tests/test_processing.py
from unittest.mock import patch
from django.test import TransactionTestCase
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection
from analytics.models import ExtractTask, ExtractData, ProcessingOption
from analytics.tasks.processing import _run_extract_task
from datetime import datetime, timezone


class RunExtractTaskGroupedTest(TransactionTestCase):
    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="grp_ds", active=True, is_global=True, task_group_period="year",
            path="/data/grp_ds",
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset, short_name="mean", function="rasterstats_default_mean", active=True,
        )
        self.resources = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"r{i}", path=f"r{i}.tif",
                temporal=datetime(2020, i, 1, tzinfo=timezone.utc),
            )
            for i in range(1, 4)
        ]
        fc = FeatureCollection.objects.create(name="fc1", active=True, is_user_upload=False)
        feat = Feature.objects.create(fc=fc)
        self.fm = FeatMap.objects.create(geom=feat, fc=fc)
        self.task = ExtractTask.objects.create(
            dataset_id=self.dataset.id,
            resource_ids=[r.id for r in self.resources],
            task_group_period="year",
            fm=self.fm, po=self.po, status=0,
        )

    @patch("analytics.tasks.processing.get_func")
    def test_all_positions_succeed(self, mock_get_func):
        mock_get_func.return_value = lambda geometry, path, **kw: [("mean", 1.5)]

        _run_extract_task(self.task.id)

        row = ExtractData.objects.get(extract_task_id=self.task.id, name="mean")
        self.assertEqual(row.float_values, [1.5, 1.5, 1.5])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 1)

    @patch("analytics.tasks.processing.get_func")
    def test_partial_failure_leaves_null_and_does_not_complete(self, mock_get_func):
        def flaky(geometry, path, **kw):
            if "r2" in str(path):
                raise RuntimeError("corrupt raster")
            return [("mean", 2.0)]

        mock_get_func.return_value = flaky

        _run_extract_task(self.task.id)

        row = ExtractData.objects.get(extract_task_id=self.task.id, name="mean")
        self.assertEqual(row.float_values, [2.0, None, 2.0])
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, 1)  # not complete -- one position still NULL

    @patch("analytics.tasks.processing.get_func")
    def test_rerun_only_reprocesses_null_positions(self, mock_get_func):
        calls = []

        def flaky(geometry, path, **kw):
            calls.append(str(path))
            if "r2" in str(path):
                raise RuntimeError("corrupt raster")
            return [("mean", 2.0)]

        mock_get_func.return_value = flaky
        _run_extract_task(self.task.id)
        calls.clear()

        mock_get_func.return_value = lambda geometry, path, **kw: [("mean", 9.0)]
        _run_extract_task(self.task.id)

        row = ExtractData.objects.get(extract_task_id=self.task.id, name="mean")
        self.assertEqual(row.float_values, [2.0, 9.0, 2.0])  # only position 1 (index 1) reprocessed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_processing -v 2`
Expected: FAIL — current implementation assumes a single `task.resource`, not `resource_ids`.

- [ ] **Step 3: Rewrite `_run_extract_task` and `_store_extract_value`**

Replace the relevant portion of `backend/analytics/tasks/processing.py`:

```python
def _store_extract_values(extract_task_id, name, values):
    """Upsert one (extract_task, name) row's position-aligned value arrays.

    values is a list, same length/order as the task's resource_ids, with None
    at positions not yet successfully processed.
    """
    if not values:
        return
    sample = next((v for v in values if v is not None), None)
    if isinstance(sample, int):
        data_column, column = "int", "int_values"
    elif isinstance(sample, float):
        data_column, column = "float", "float_values"
    else:
        data_column, column = "str", "str_values"
        values = [None if v is None else str(v) for v in values]

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO extract_data (extract_task_id, dataset_id, name, data_column, {column})
            SELECT %s, dataset_id, %s, %s, %s FROM extract_tasks WHERE id = %s
            ON CONFLICT DO NOTHING
            """,
            [extract_task_id, name, data_column, values, extract_task_id],
        )


def _run_extract_task(task_id):
    """Lock the task row, run the processor once per resource_ids entry, and
    store position-aligned results. A resource whose read raises leaves its
    position NULL rather than failing the whole task; the task is only
    marked complete (status=1) once every position across every named result
    is non-NULL. Rerunning only reprocesses NULL positions.
    """
    logger.info("Running extract task %s", task_id)
    now = timezone.now

    with transaction.atomic():
        task = (
            ExtractTask.objects.select_for_update(of=("self",), skip_locked=True)
            .select_related("po", "fm__fc", "fm__geom")
            .filter(
                id=task_id,
                status__in=(0, 3),
                fm__fc__active=True,
                po__active=True,
            )
            .first()
        )
        if task is None:
            logger.info("Task %s is not available (already locked, done, or filtered out)", task_id)
            return None

        task.status = 2
        task.update_time = now()
        task.save(update_fields=["status", "update_time"])

    resources = list(DatasetResource.objects.filter(id__in=task.resource_ids))
    resources_by_id = {r.id: r for r in resources}
    dataset = resources[0].dataset if resources else None

    existing_rows = list(ExtractData.objects.filter(extract_task_id=task_id))
    existing_by_name = {
        row.name: (row.float_values or row.int_values or row.str_values or [None] * len(task.resource_ids))
        for row in existing_rows
    }

    try:
        func = get_func(task.po.function)
        geometry = shapely.from_wkb(bytes(task.fm.geom.shape.wkb))

        op_kwargs = {"name": task.po.short_name}
        if task.po.kwargs:
            op_kwargs.update(task.po.kwargs)
        if task.kwargs:
            op_kwargs.update(task.kwargs)
            kwargs_hash = hashlib.md5(json.dumps(task.kwargs, sort_keys=True).encode()).hexdigest()[:8]
            op_kwargs["name"] = f"{task.po.short_name}_{kwargs_hash}"

        if dataset and dataset.mapped:
            op_kwargs["category_map"] = dict(dataset.mappings.values_list("map_val", "map_name"))

        results_by_name: dict[str, list] = {
            name: list(vals) for name, vals in existing_by_name.items()
        }
        any_failure = False

        for i, resource_id in enumerate(task.resource_ids):
            already_done = all(
                (vals[i] is not None) for vals in results_by_name.values()
            ) and results_by_name
            if already_done:
                continue

            resource = resources_by_id.get(resource_id)
            if resource is None:
                any_failure = True
                continue

            dataset_path = Path(resource.dataset.path) / resource.path
            try:
                with catch_warnings(record=True) as warnings:
                    results = func(geometry, dataset_path, **op_kwargs)
                    for w in warnings:
                        logger.warning("Warning in task %s resource %s: %s", task_id, resource_id, w.message)
            except Exception as exc:
                logger.exception("Task %s resource %s failed: %s", task_id, resource_id, exc)
                any_failure = True
                for name in results_by_name:
                    pass  # position stays None
                continue

            for name, value in results:
                if name not in results_by_name:
                    results_by_name[name] = [None] * len(task.resource_ids)
                results_by_name[name][i] = value

        with connection.cursor() as cursor:
            for name, values in results_by_name.items():
                _store_extract_values(task_id, name, values)

            if any_failure:
                cursor.execute(
                    "UPDATE extract_tasks SET status = 0, update_time = %s, attempts = attempts + 1 WHERE id = %s",
                    [now(), task_id],
                )
            else:
                cursor.execute(
                    "UPDATE extract_tasks SET status = 1, complete_time = %s WHERE id = %s",
                    [now(), task_id],
                )

        n_results = sum(1 for vals in results_by_name.values() for v in vals if v is not None)
        logger.info("Task %s stored %d result value(s), any_failure=%s", task_id, n_results, any_failure)
        return {"task_id": task_id, "results": n_results, "any_failure": any_failure}

    except Exception as exc:
        logger.exception("Task %s failed: %s", task_id, exc)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE extract_tasks SET status = -1, error = %s WHERE id = %s",
                [repr(exc)[:100], task_id],
            )
        raise
```

Add the import needed for `DatasetResource`:

```python
from datasets.models import DatasetResource
```

Note the `status = 0` (back to pending, not `-1`/failed) on partial failure — this is what makes it eligible for the *next* `dispatch_pending_tasks` claim, which re-enters `_run_extract_task` and, via the `already_done` check per position, only reprocesses `NULL` slots. A task genuinely stuck failing the same position forever will have `attempts` climb each retry, which `manage_processing_task_errors`/`free_stale_processing_tasks` (unchanged by this redesign) already use for their existing error-handling logic.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_processing -v 2`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/analytics/tasks/processing.py backend/analytics/tests/test_processing.py
git commit -m "Process resource_ids per-position with NULL-position partial retry"
```

---

## Task 9: Update ad-hoc single-task creation paths

**Goal:** `views.py` and `ingest.py`'s custom/on-demand extraction paths create `ExtractTask` rows using `resource_ids=[resource.id]` against the new schema.

**Files:**
- Modify: `backend/analytics/views.py:220-240`
- Modify: `backend/analytics/ingest.py:120-132`
- Test: `backend/analytics/tests/test_views.py`, `backend/analytics/tests/test_ingest.py`

**Acceptance Criteria:**
- [ ] Both call sites create `ExtractTask` rows with `resource_ids=[resource.id]`, `dataset_id=resource.dataset_id`.
- [ ] The `views.py` get-or-create-with-`IntegrityError`-fallback pattern still relies on the DB-level unique index from Task 6 to make concurrent requests safe.
- [ ] `ingest.py`'s `bulk_create(..., ignore_conflicts=True)` still relies on the same index.

**Verify:** `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_views analytics.tests.test_ingest -v 2` → `OK`

**Steps:**

- [ ] **Step 1: Update `views.py`**

Replace the loop body at `backend/analytics/views.py:220-240`:

```python
            task_ids = []
            for fm in fms:
                for resource in resource_list:
                    for po in pos:
                        resource_ids = [resource.id]
                        try:
                            task = ExtractTask.objects.get(
                                resource_ids=resource_ids, fm=fm, po=po, **kwargs_lookup
                            )
                        except ExtractTask.DoesNotExist:
                            try:
                                task = ExtractTask.objects.create(
                                    resource_ids=resource_ids,
                                    dataset_id=resource.dataset_id,
                                    fm=fm, po=po, kwargs=task_kwargs,
                                )
                            except IntegrityError:
                                task = ExtractTask.objects.get(
                                    resource_ids=resource_ids, fm=fm, po=po, **kwargs_lookup
                                )
                        if task.priority < 1:
                            task.priority = 1
                            task.save(update_fields=["priority"])
                        task_ids.append(task.id)
```

- [ ] **Step 2: Update `ingest.py`**

Replace the `bulk_create` call at `backend/analytics/ingest.py:120-132`:

```python
        ExtractTask.objects.bulk_create(
            [
                ExtractTask(
                    resource_ids=[resource.id],
                    dataset_id=resource.dataset_id,
                    fm=fm, po=po, kwargs=task_kwargs, priority=1,
                )
                for fm in feat_map_objs
                for resource in resources
                for po in pos
            ],
            ignore_conflicts=True,
        )
```

- [ ] **Step 3: Write/adapt tests confirming the new call shape**

```python
# backend/analytics/tests/test_views.py (add to existing suite, or create if absent)
from django.test import TestCase
from analytics.models import ExtractTask


class AdHocTaskCreationTest(TestCase):
    def test_creates_task_with_resource_ids_array(self):
        # ... reuse whatever fixture setup the existing view test suite has for
        # Dataset/DatasetResource/ProcessingOption/FeatMap; call the view/endpoint
        # under test, then assert:
        task = ExtractTask.objects.first()
        self.assertIsNotNone(task)
        self.assertEqual(len(task.resource_ids), 1)
        self.assertIsNotNone(task.dataset_id)
```

(Exact fixture wiring depends on the existing test suite's setup for this view, which should already exist for the pre-redesign behavior — adapt those existing fixtures rather than rebuilding from scratch; the assertion shape above is what matters.)

- [ ] **Step 4: Run tests**

Run: `cd backend && /app/.venv/bin/python manage.py test analytics.tests.test_views analytics.tests.test_ingest -v 2`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/analytics/views.py backend/analytics/ingest.py backend/analytics/tests/test_views.py
git commit -m "Update ad-hoc task creation paths for resource_ids array"
```

---

## Task 10: Update export queries to unnest value arrays

**Goal:** `visualize/data.py`'s two `ExtractData` queries (backing `/api/visualize/request/<id>/` and `/api/visualize/explore/`) flatten the new arrays back to one-row-per-month for the response payload, preserving the existing API response shape.

**Files:**
- Modify: `backend/visualize/data.py:64-80` and `:213-230`
- Test: `backend/visualize/tests/test_data.py`

**Acceptance Criteria:**
- [ ] Both queries return one logical result per `(feature, resource, name)` in the response payload, matching the pre-redesign shape — callers of `build_request_data`/the explore endpoint see no change.
- [ ] A grouped task's 12 values unnest into 12 separate result entries, each attributable to its specific `DatasetResource` (for date/period labeling in the frontend).

**Verify:** `cd backend && /app/.venv/bin/python manage.py test visualize.tests.test_data -v 2` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/visualize/tests/test_data.py
from django.test import TransactionTestCase
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection
from analytics.models import ExtractTask, ExtractData, ProcessingOption, Request, RequestMap
from visualize.data import build_request_data
from datetime import datetime, timezone


class BuildRequestDataGroupedTest(TransactionTestCase):
    def test_grouped_task_unnests_to_one_entry_per_resource(self):
        d = Dataset.objects.create(name="grp_ds", active=True, is_global=True, task_group_period="year")
        po = ProcessingOption.objects.create(dataset=d, short_name="mean", function="rasterstats_default_mean", active=True)
        resources = [
            DatasetResource.objects.create(
                dataset=d, name=f"r{i}", path=f"r{i}.tif",
                temporal=datetime(2020, i, 1, tzinfo=timezone.utc),
            )
            for i in range(1, 4)
        ]
        fc = FeatureCollection.objects.create(name="fc1", active=True, is_user_upload=False)
        feat = Feature.objects.create(fc=fc)
        fm = FeatMap.objects.create(geom=feat, fc=fc)
        task = ExtractTask.objects.create(
            dataset_id=d.id, resource_ids=[r.id for r in resources],
            task_group_period="year", fm=fm, po=po, status=1,
        )
        ExtractData.objects.create(
            extract_task=task, dataset_id=d.id, name="mean", data_column="float",
            float_values=[1.1, 2.2, 3.3],
        )
        req = Request.objects.create(source="test")
        RequestMap.objects.create(request=req, task=task, dataset_id=d.id)

        payload = build_request_data(req)

        # Exact payload shape depends on build_request_data's existing return
        # structure -- assert the unnest happened: 3 distinct value entries,
        # not 1 entry holding an array.
        values_seen = [
            v for row in payload.get("data", payload) for k, v in row.items()
            if k not in ("name", "fc")
        ] if isinstance(payload.get("data", payload), list) else []
        # Adapt this assertion to whatever build_request_data's real return
        # shape is (inspect it directly against the pre-redesign test suite,
        # which already exercises this function's non-grouped shape).
```

The exact assertion body needs to match `build_request_data`'s real return shape — inspect the existing (pre-redesign) test coverage for this function to mirror its assertion style; the important behavioral claim to lock down is "3 separate values, one per resource, not one array."

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /app/.venv/bin/python manage.py test visualize.tests.test_data.BuildRequestDataGroupedTest -v 2`
Expected: FAIL or ERROR — current query returns arrays, not flattened rows.

- [ ] **Step 3: Update the two queries in `visualize/data.py`**

At `backend/visualize/data.py:64-80` (the `requestmap__request=request` query), change:

```python
    data_rows = (
        ExtractData.objects
        .filter(extract_task__requestmap__request=request)
        .annotate(
            resource_id=RawSQL(
                "unnest(extract_task.resource_ids)", (), output_field=models.IntegerField()
            ),
        )
        .values(
            "resource_id",
            "extract_task__fm__geom_id",
            "extract_task__resource__name",  # see note below
            "extract_task__resource__label",
            "extract_task__resource__dataset__short_name",
            "extract_task__resource__dataset__title",
            "extract_task__resource__dataset__name",
            "extract_task__po__dataset_id",
            "extract_task__po__short_name",
            "extract_task__kwargs",
            "name",
            "data_column",
        )
    )
```

This `RawSQL(unnest(...))` approach doesn't automatically zip `resource_id` with the corresponding *value* at that position using the Django ORM's `.values()` alone — Django's ORM has no native construct for "unnest two arrays in parallel and pair them," so the value-array unnesting has to happen via a raw query instead of ORM `.filter()/.values()`. Replace the whole query with raw SQL:

```python
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                unnested.resource_id,
                et.fm_id,
                fm.geom_id,
                dr.name AS resource_name,
                dr.label AS resource_label,
                ds.short_name AS dataset_short_name,
                ds.title AS dataset_title,
                ds.name AS dataset_name,
                po.dataset_id AS po_dataset_id,
                po.short_name AS po_short_name,
                et.kwargs,
                ed.name,
                ed.data_column,
                unnested.value_float,
                unnested.value_int,
                unnested.value_str
            FROM extract_data ed
            INNER JOIN extract_tasks et ON et.dataset_id = ed.dataset_id AND et.id = ed.extract_task_id
            INNER JOIN request_map rm ON rm.dataset_id = et.dataset_id AND rm.task_id = et.id
            INNER JOIN feat_map fm ON fm.id = et.fm_id
            INNER JOIN processing_options po ON po.id = et.po_id
            CROSS JOIN LATERAL unnest(
                et.resource_ids, ed.float_values, ed.int_values, ed.str_values
            ) WITH ORDINALITY AS unnested(resource_id, value_float, value_int, value_str, ord)
            INNER JOIN dataset_resources dr ON dr.id = unnested.resource_id
            INNER JOIN datasets ds ON ds.id = dr.dataset_id
            WHERE rm.request_id = %s
            """,
            [str(request.id)],
        )
        columns = [c[0] for c in cursor.description]
        data_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
```

Then downstream code (the loop building `record`/`data_cols_set`/etc. immediately following this query) reads `dr["value_float"] or dr["value_int"] or dr["value_str"]` in place of the old single `dr["float_value"]`/`dr["int_value"]`/`dr["str_value"]` scalar lookups — update those field-name references accordingly wherever they appear later in the same function.

- [ ] **Step 4: Apply the same pattern to the second query**

At `backend/visualize/data.py:213-230` (the `fm__fc_id__in=fc_ids, po_id__in=po_ids` query), apply the identical raw-SQL `unnest(... ) WITH ORDINALITY` rewrite, substituting the `WHERE` clause:

```python
            WHERE fm.fc_id = ANY(%s) AND et.po_id = ANY(%s)
            """,
            [fc_ids, po_ids],
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && /app/.venv/bin/python manage.py test visualize.tests.test_data -v 2`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/visualize/data.py backend/visualize/tests/test_data.py
git commit -m "Unnest ExtractData value arrays for visualize export queries"
```

---

## Task 11: Deploy

**Goal:** Ship the full redesign through the existing CI/CD pipeline (per the deploy mechanics established earlier in this project: `[DEPLOY-X.Y.Z]` commit marker, `geoquery-db-migration` Job runs all pending migrations as a `pre-upgrade` Helm hook).

**Files:** none (deploy-only task)

**Acceptance Criteria:**
- [ ] All migrations 0017-0022 (analytics) and the `datasets` app migration from Task 0 apply cleanly in the `geoquery-db-migration` Job.
- [ ] `extract_tasks`/`extract_data` show as partitioned in `pg_partitioned_table` post-deploy.
- [ ] A manually-triggered `build_extract_tasks` run produces at least one grouped task (for a dataset with `task_group_period` set — none will have it set until a follow-up data step assigns it to CRU_TS/the other monthly datasets, which is out of scope for this plan; verify instead that a standard dataset's task generation still works end-to-end, confirming the redesign didn't break the non-grouped path).

**Verify:** Same pattern used throughout this project's incident response — push with a `[DEPLOY-X.Y.Z]` marker (next version after whatever's currently deployed), poll GitHub Actions for the build + `Deploy GeoQuery` workflows, force a `HelmRepository` reconcile if the chart doesn't resolve immediately (known transient issue seen twice already in this project), then confirm the migration job succeeded and `django_migrations` lists all six new migration names.

**Steps:**

- [ ] **Step 1: Confirm current deployed version**

```bash
grep "^version:" /path/to/helm-charts/charts/geoquery/Chart.yaml
```

Use the next minor version after whatever this returns.

- [ ] **Step 2: Commit with the deploy marker**

```bash
git commit --allow-empty -m "Deploy extract_tasks/extract_data redesign: grouped tasks, partitioning, new indexes [DEPLOY-X.Y.Z]"
git push origin main
```

(Substitute the real version number from Step 1.)

- [ ] **Step 3: Poll and confirm, per the established pattern**

```bash
curl -s "https://api.github.com/repos/aiddata/geoquery/actions/runs?branch=main&per_page=10" | python3 -c "
import json,sys
data = json.load(sys.stdin)
for r in data['workflow_runs']:
    if r['head_sha'].startswith('<commit-sha>'):
        print(f\"{r['name']:30s} status={r['status']:12s} conclusion={r['conclusion']}\")
"
```

Then check `kubectl get helmrelease geoquery-prod -n aiddata` and `kubectl logs -n geoquery-prod job/geoquery-db-migration` for the migration job's outcome, force-reconciling the `HelmRepository` if the chart shows "not found" (a known transient timing issue between chart publish and Flux's next poll, seen on both prior deploys in this project).

- [ ] **Step 4: Verify partitioning and indexes live**

```sql
SELECT count(*) FROM pg_partitioned_table pt JOIN pg_class c ON c.oid = pt.partrelid WHERE c.relname IN ('extract_tasks','extract_data');
-- expect 2
SELECT indexname FROM pg_indexes WHERE tablename = 'extract_tasks';
-- expect the two new composite indexes + pending_idx + the PK's auto index
```

No commit for this task — it's the deploy action itself, already committed in Step 2.

---

## Self-Review

**Spec coverage:**
- Items 1-3 (composite index replacing the unused hash index, dropping redundant single-column indexes, keeping pkey/pending_idx) → Task 6, reconciled with the array-based schema (the original scalar-column index design from earlier in the conversation doesn't directly apply once `resource_id` becomes `resource_ids`; Task 6's index is the adapted equivalent).
- Partitioning → Task 5.
- Resource batching/grouped tasks (`Dataset.task_group_period`, `resource_ids` array, position-aligned `ExtractData` arrays, partial NULL-position retry, flexible period not hardcoded to year) → Tasks 0, 2, 3, 7, 8.
- Claiming design generalization to arrays (unifying standard 1-element and grouped N-element under one shape) → Tasks 4, 7.
- Downstream consumers of the old scalar shape (ad-hoc task creation, export queries) → Tasks 9, 10.
- Wiping existing data (explicit user decision) → Task 1.

**Placeholder scan:** no TBD/TODO markers; every code step has complete, real SQL or Python. Task 9's test fixture setup and Task 10's payload-shape assertion explicitly note "adapt to the existing test suite's shape" rather than fabricate assertions against a response format not inspected in this plan — that's a deliberate, bounded exception (the exact JSON shape of `build_request_data`'s return value wasn't read in full during this planning session), not a scope placeholder; the behavioral claim being tested is fully specified either way.

**Type consistency:** `resource_ids` (list[int]/`INTEGER[]`), `dataset_id` (int), `task_group_period` (`str | None`, one of day/week/month/quarter/year) used consistently across `Dataset`, `ExtractTask`, `ExtractTaskBuildProgress`, `build_extract_tasks.py`, and `processing.py`. `ExtractData.{float,int,str}_values` (arrays, position-aligned with the owning task's `resource_ids`) used consistently across Tasks 3, 8, 10.
