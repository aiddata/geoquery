# Extract Data/Tasks Index Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink two of the largest remaining storage line items in the extract-tasks-redesign schema — `extract_data`'s redundant surrogate PK, and `extract_tasks`' largest index (`extract_tasks_fm_po_resources_null_kwargs_idx`, 34% of the table's footprint) — without changing any observable query behavior.

**Architecture:** Two independent, unrelated-table changes: (1) replace `ExtractData`'s auto `BigAutoField` id with a natural composite primary key `(dataset_id, extract_task_id, name)`, eliminating a redundant surrogate-key index; (2) add a stored generated column `resource_ids_hash` on `extract_tasks` (`hashtext(resource_ids::text)`) and rebuild both `resource_ids`-keyed unique indexes to use the hash instead of the raw array, then update the one call site (`views.py`'s get-or-create loop) that needs an explicit hash filter to actually benefit from the smaller index at query time.

**Tech Stack:** Django 5.2.17 (first use in this codebase of `CompositePrimaryKey` and `GeneratedField`, both added in 5.x), PostgreSQL 17 (CNPG-managed in prod), hand-written raw-SQL migrations with `state_operations` (established pattern for partitioned-table DDL Django's autodetector can't handle — see every migration from 0017 onward).

**User decisions (already made):**
- Confirmed `(dataset_id, extract_task_id, name)` as `ExtractData`'s new PK — verified 0 current NULL `name` values and 0 duplicate `(dataset_id, extract_task_id, name)` combinations in live production data.
- Confirmed the hash-the-array approach for `extract_tasks` over a full-tuple hash index, specifically because it keeps `dataset_id`/`fm_id`/`po_id` as plain columns usable by ordinary multi-column `WHERE` clauses — avoiding the exact failure mode that made the original `extract_tasks_resource_fm_po_kwargs_hash_idx` (1.8GB, zero reads) useless.
- User explicitly ruled out the two other explored size-reduction strategies (lazy/on-demand task generation, decade-level grouping) as out of scope for now — this plan is index/schema optimization only, not generation-strategy changes.
- Deploy to production is a separate, explicitly gated final task (Task 4) — production `extract_data` currently has 1.27M+ rows and is being written to continuously by live `processing-worker` pods, unlike the original redesign's deploy which safely wiped empty tables first.

---

## File Structure

- `backend/analytics/models.py` — `ExtractData` (composite PK, `name` becomes non-nullable), `ExtractTask` (new `resource_ids_hash` `GeneratedField`)
- `backend/analytics/migrations/0023_extractdata_composite_pk.py` — new, hand-written
- `backend/analytics/migrations/0024_extracttask_resource_ids_hash.py` — new, hand-written
- `backend/analytics/admin.py` — `ExtractDataAdmin` (drop `"id"` references)
- `backend/analytics/views.py` — `RequestView.post`'s get-or-create loop (add `resource_ids_hash` filter)
- `backend/analytics/tests/test_models.py` — extend with composite-PK assertions
- `backend/analytics/tests/test_views.py` — update the one test that hardcodes exact `.get()`/`.create()` call kwargs
- `backend/analytics/tests/test_processing.py`, `backend/analytics/tests/test_merge.py`, `backend/visualize/tests/test_data.py` — no code changes expected, but must be re-run as regression proof (all construct `ExtractData` via `.create()`, none reference `.id`/`.pk`)

---

### Task 0: ExtractData composite primary key

**Goal:** `ExtractData` uses `(dataset_id, extract_task_id, name)` as its primary key instead of an auto-generated `id`, with all existing read/write code paths (including the fetch-then-update rerun path) proven still correct.

**Files:**
- Modify: `backend/analytics/models.py:149-182` (the `ExtractData` class)
- Create: `backend/analytics/migrations/0023_extractdata_composite_pk.py`
- Modify: `backend/analytics/admin.py:51-60` (`ExtractDataAdmin`)
- Modify: `backend/analytics/tests/test_models.py` (add composite-PK assertions to `ExtractDataArraysTest` or a new test class in the same file)

**Acceptance Criteria:**
- [ ] `ExtractData` has no `id` column at the DB level (`information_schema.columns` confirms it's gone)
- [ ] `(dataset_id, extract_task_id, name)` is the actual `PRIMARY KEY` constraint at the DB level (`information_schema.table_constraints`/`key_column_usage` confirms)
- [ ] `name` is `NOT NULL` at the DB level
- [ ] `ExtractDataAdmin` no longer references the removed `id` field anywhere
- [ ] **All** existing tests in `analytics.tests.test_processing`, `analytics.tests.test_merge`, `visualize.tests.test_data`, and `analytics.tests.test_models` still pass unmodified — in particular `test_rerun_only_reprocesses_null_positions` and `test_rerun_results_count_is_not_inflated_by_overlapping_name` in `test_processing.py`, which exercise the fetch-an-existing-row-then-`.save()` code path and are the concrete proof that Django's insert-vs-update determination still works correctly for a model with no auto field

**Verify:** `sudo docker compose run --rm backend uv run python manage.py test analytics.tests.test_models analytics.tests.test_processing analytics.tests.test_merge visualize.tests.test_data -v 2` → all pass, 0 failures, 0 errors

**Steps:**

- [ ] **Step 1: Read the current code before changing anything**

Read `backend/analytics/models.py:149-182` (current `ExtractData` class, reproduced below for reference — confirm it still matches before editing, the file may have drifted):

```python
class ExtractData(models.Model):
    """Extract data table for storing extraction results.

    One row per (extract_task, name) -- see ExtractTask.resource_ids. Values
    are arrays position-aligned with the owning task's resource_ids: index i
    here is the result for resource_ids[i].

    Two independent levels of NULL, not to be conflated:
    - Column-level (float_values/int_values/str_values each nullable): only
      ONE of the three is actually used per row, matching data_column --
      exactly like the old scalar float_value/int_value/str_value columns
      this replaced, where a row's value had one type and the other two
      columns were simply irrelevant to it. The other two stay NULL, not an
      array of NULLs.
    - Element-level (each array's own field is null=True): within whichever
      one column is in use, a NULL at position i means resource_ids[i] still
      needs (re)processing -- see analytics.tasks.processing._run_extract_task.
    """

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

Also read `backend/analytics/tasks/processing.py` in full, specifically the section that merges results into `ExtractData` rows (the `existing_by_name` dict lookup and the branch that either mutates an existing fetched row or constructs `ExtractData(...)` fresh) — you need to understand exactly how rows are constructed and saved before changing what the primary key is made of, since this is the code path most likely to be affected by the PK change.

- [ ] **Step 2: Update the model**

Replace the `ExtractData` class in `backend/analytics/models.py:149-182` with:

```python
class ExtractData(models.Model):
    """Extract data table for storing extraction results.

    One row per (extract_task, name) -- see ExtractTask.resource_ids. Values
    are arrays position-aligned with the owning task's resource_ids: index i
    here is the result for resource_ids[i].

    Two independent levels of NULL, not to be conflated:
    - Column-level (float_values/int_values/str_values each nullable): only
      ONE of the three is actually used per row, matching data_column --
      exactly like the old scalar float_value/int_value/str_value columns
      this replaced, where a row's value had one type and the other two
      columns were simply irrelevant to it. The other two stay NULL, not an
      array of NULLs.
    - Element-level (each array's own field is null=True): within whichever
      one column is in use, a NULL at position i means resource_ids[i] still
      needs (re)processing -- see analytics.tasks.processing._run_extract_task.

    Primary key is the natural (dataset_id, extract_task_id, name) tuple, not
    a surrogate id -- (extract_task, name) was always the real uniqueness
    constraint (confirmed: 0 duplicates in production data before this
    migration), and dataset_id must lead per Postgres's partition-key
    requirement for any PK/unique constraint on this LIST-partitioned table.
    Dropping the surrogate id removes its own now-redundant PK index
    entirely, rather than keeping it alongside a second uniqueness
    constraint that would give none of the storage benefit.
    """

    pk = models.CompositePrimaryKey("dataset_id", "extract_task", "name")
    extract_task = models.ForeignKey(
        ExtractTask, on_delete=models.CASCADE, db_column="extract_task_id"
    )
    dataset_id = models.IntegerField()
    name = models.CharField(max_length=100)
    data_column = models.CharField(max_length=100, blank=True, null=True)
    float_values = ArrayField(models.FloatField(null=True), blank=True, null=True)
    int_values = ArrayField(models.BigIntegerField(null=True), blank=True, null=True)
    str_values = ArrayField(models.CharField(max_length=100, null=True), blank=True, null=True)

    class Meta:
        db_table = "extract_data"

    def __str__(self):
        return f"ExtractData for Task {self.extract_task_id}: {self.name}"
```

Note `name` lost `blank=True, null=True` (a PK component cannot be NULL) and `pk = models.CompositePrimaryKey("dataset_id", "extract_task", "name")` was added, referencing the *field* names (`extract_task`, not the db column `extract_task_id`).

**Before proceeding**, verify `models.CompositePrimaryKey` is the correct Django 5.2.17 API by checking `django.db.models.__init__` in the installed package (`python -c "from django.db.models import CompositePrimaryKey; print(CompositePrimaryKey)"` inside the backend container, or read the source at the installed site-packages path) — this is the first use of this API in this codebase, so confirm the exact argument convention (field names vs db columns) empirically rather than trusting this plan's syntax blindly. If the real API differs from what's shown above, use the real signature and note the correction when you commit.

- [ ] **Step 3: Write the migration**

Create `backend/analytics/migrations/0023_extractdata_composite_pk.py`:

```python
from django.db import migrations, models


# extract_data currently has ~1.27M rows in production and growing --
# unlike migration 0017's wipe-first approach, this ALTERs a live,
# non-empty table. Both operations below are cheap at this row count
# (NOT NULL validation and PK constraint validation are both single
# sequential scans, no full rewrite), but on a much larger table in the
# future this pattern would need CONCURRENTLY-style staging (add the
# constraint NOT VALID, then VALIDATE CONSTRAINT separately) rather than
# a straight ADD CONSTRAINT -- not needed yet at current volume.
_FORWARD_SQL = """
    ALTER TABLE extract_data ALTER COLUMN name SET NOT NULL;
    ALTER TABLE extract_data DROP CONSTRAINT extract_data_pkey;
    ALTER TABLE extract_data ADD PRIMARY KEY (dataset_id, extract_task_id, name);
    ALTER TABLE extract_data DROP COLUMN id;
"""

# Re-adding the surrogate id column on reverse would need a fresh identity
# sequence and wouldn't reconstruct the original values -- reversing this
# migration is only meaningful before any data has been written under the
# new schema. Matches the same one-way-in-practice posture as migration
# 0017's wipe (documented there as acceptable given the data is
# regenerable); here reversal is simply unsupported rather than lossy.
_REVERSE_SQL = migrations.RunSQL.noop


class Migration(migrations.Migration):
    """
    Replaces ExtractData's surrogate BigAutoField id with the natural
    (dataset_id, extract_task_id, name) composite key. (extract_task, name)
    was always the real uniqueness constraint (0 duplicates confirmed in
    production data); dataset_id leads because Postgres requires the
    partition key in any PK/unique constraint on a partitioned table
    (extract_data is LIST-partitioned on dataset_id, migration 0021).

    Dropping id also drops its own now-redundant PK index -- this is the
    entire point of the migration, not a side effect to work around.
    """

    dependencies = [
        ("analytics", "0022_extracttask_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
            state_operations=[
                migrations.AlterField(
                    model_name="extractdata",
                    name="name",
                    field=models.CharField(max_length=100),
                ),
                migrations.RemoveField(
                    model_name="extractdata",
                    name="id",
                ),
                migrations.AddField(
                    model_name="extractdata",
                    name="pk",
                    field=models.CompositePrimaryKey("dataset_id", "extract_task", "name"),
                ),
            ],
        ),
    ]
```

**Before finalizing**, run `python manage.py makemigrations analytics --check --dry-run` inside the backend container after this migration is applied, to see whether Django detects any remaining state drift between `state_operations` and the real model definition from Step 2 — some drift is expected and already-documented as pre-existing/harmless in this codebase (the `ExtractTaskBuildRun`/`extracttaskbuildprogress.id` drift noted in the original redesign's final review), but confirm nothing NEW and unexpected shows up specifically related to `ExtractData`.

- [ ] **Step 4: Update the admin**

In `backend/analytics/admin.py`, replace the `ExtractDataAdmin` class (currently lines 51-60):

```python
@admin.register(ExtractData)
class ExtractDataAdmin(admin.ModelAdmin):
    list_display = (
        "dataset_id",
        "extract_task_id",
        "name",
        "data_column",
        "float_values",
        "int_values",
        "str_values",
    )
    list_filter = ("dataset_id", "name")
    search_fields = ("name",)
```

(`search_fields` drops `dataset_id`/`extract_task_id` since Django admin's `search_fields` needs text-searchable fields, not integers, for its `icontains` default lookup — `"id"` worked before only because Django admin special-cases exact-match on `pk`/numeric-looking search terms; `name` alone is the correct text-search field here.)

- [ ] **Step 5: Add explicit model-level tests**

Add to `backend/analytics/tests/test_models.py` (in the existing `ExtractDataArraysTest` class):

```python
    def test_composite_primary_key_at_db_level(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON kcu.constraint_name = tc.constraint_name
                    AND kcu.table_name = tc.table_name
                WHERE tc.table_name = 'extract_data' AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
            """)
            pk_columns = [row[0] for row in cursor.fetchall()]
        self.assertEqual(pk_columns, ["dataset_id", "extract_task_id", "name"])

    def test_id_column_removed(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT count(*) FROM information_schema.columns
                WHERE table_name = 'extract_data' AND column_name = 'id'
            """)
            count = cursor.fetchone()[0]
        self.assertEqual(count, 0, "id column should be removed")

    def test_name_is_not_null_at_db_level(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT is_nullable FROM information_schema.columns
                WHERE table_name = 'extract_data' AND column_name = 'name'
            """)
            is_nullable = cursor.fetchone()[0]
        self.assertEqual(is_nullable, "NO")
```

- [ ] **Step 6: Run the migration and full regression suite**

```
sudo docker compose run --rm backend uv run python manage.py test analytics.tests.test_models analytics.tests.test_processing analytics.tests.test_merge visualize.tests.test_data -v 2
```

Expected: all tests pass, 0 failures, 0 errors. Pay particular attention to `test_rerun_only_reprocesses_null_positions` and `test_rerun_results_count_is_not_inflated_by_overlapping_name` in the output — these are the concrete proof the composite PK doesn't break the fetch-then-update path. If either fails, do not work around it by reverting the PK change — investigate whether `force_insert`/`force_update` needs to be passed explicitly in `processing.py`'s save calls (Django's insert-vs-update determination is based on `instance._state.adding`, which should already be correctly set by whether the instance was freshly constructed vs loaded via a queryset fetch — but verify this empirically rather than assuming).

- [ ] **Step 7: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/0023_extractdata_composite_pk.py backend/analytics/admin.py backend/analytics/tests/test_models.py
git commit -m "Replace ExtractData surrogate id with natural composite primary key"
```

---

### Task 1: extract_tasks resource_ids_hash generated column and index rebuild

**Goal:** `extract_tasks` gains a stored generated column `resource_ids_hash` (`hashtext(resource_ids::text)`), and both `resource_ids`-keyed unique indexes are rebuilt to use it instead of the raw array, shrinking the largest single index in the schema.

**Files:**
- Modify: `backend/analytics/models.py` (the `ExtractTask` class — add `resource_ids_hash` field)
- Create: `backend/analytics/migrations/0024_extracttask_resource_ids_hash.py`
- Modify: `backend/analytics/tests/test_models.py` (add generated-column assertions)

**Acceptance Criteria:**
- [ ] `resource_ids_hash` exists as an `integer` column on `extract_tasks`, `GENERATED ALWAYS ... STORED`
- [ ] Inserting a row with a given `resource_ids` array automatically populates `resource_ids_hash` with `hashtext(resource_ids::text)` — verified by direct comparison in a test
- [ ] `extract_tasks_fm_po_resources_null_kwargs_idx` is rebuilt on `(dataset_id, fm_id, po_id, resource_ids_hash)` instead of `(..., resource_ids)`
- [ ] `extract_tasks_fm_po_resources_kwargs_hash_idx` is rebuilt on `(dataset_id, fm_id, po_id, resource_ids_hash, MD5(kwargs::text))` instead of `(..., resource_ids, ...)`
- [ ] Both indexes remain `UNIQUE`, with the same `WHERE kwargs IS NULL`/`WHERE kwargs IS NOT NULL` partial conditions as before
- [ ] `extract_tasks_pending_idx` is untouched (unrelated to this change)
- [ ] Total size of the two rebuilt indexes is smaller than before the migration, verified by direct measurement against a realistic-scale test dataset (see Step 5)
- [ ] All existing tests in `analytics.tests.test_build_extract_tasks` still pass — this command's own `ON CONFLICT`/anti-join logic against `extract_tasks` must be unaffected

**Verify:** `sudo docker compose run --rm backend uv run python manage.py test analytics.tests.test_models analytics.tests.test_build_extract_tasks -v 2` → all pass

**Steps:**

- [ ] **Step 1: Read current code**

Read `backend/analytics/models.py`'s `ExtractTask` class in full (currently defines `resource_ids = ArrayField(models.IntegerField())` among its fields) and `backend/analytics/migrations/0022_extracttask_indexes.py` in full (reproduced in this plan's header research, but re-read the live file — it may have drifted).

- [ ] **Step 2: Add the field to the model**

In `backend/analytics/models.py`, in the `ExtractTask` class, add (immediately after the existing `resource_ids` field declaration):

```python
    resource_ids_hash = models.GeneratedField(
        expression=Func(
            Cast("resource_ids", output_field=models.TextField()),
            function="hashtext",
        ),
        output_field=models.IntegerField(),
        db_persist=True,
    )
```

Add the required imports at the top of `backend/analytics/models.py`:

```python
from django.db.models import Func
from django.db.models.functions import Cast
```

**Before finalizing**, verify this expression actually produces `hashtext(CAST(resource_ids AS text))` (semantically equivalent to `hashtext(resource_ids::text)`) by checking the generated SQL — e.g. via `str(ExtractTask._meta.get_field("resource_ids_hash").expression.as_sql(...))` in a shell, or simply by comparing behavior in the test written in Step 4 below. This is the first use of `GeneratedField` in this codebase; confirm the `Func`/`Cast` combination compiles to the intended SQL rather than assuming.

Also update the `ExtractTask` class docstring to mention the new field, following the same documentation style as the rest of the class (explain WHY it exists — mirrors the existing composite-index migration's own rationale, not a restatement of what a generated column is).

- [ ] **Step 3: Write the migration**

Create `backend/analytics/migrations/0024_extracttask_resource_ids_hash.py`:

```python
from django.db import migrations, models
from django.db.models import Func
from django.db.models.functions import Cast


# Adds the hashed column and rebuilds both resource_ids-keyed unique
# indexes to use it instead of the raw array. extract_tasks currently has
# tens of millions of rows and counting in production -- unlike migration
# 0022 (which built its indexes against an empty, just-wiped table), this
# runs against a live, growing, partitioned table. CREATE INDEX CONCURRENTLY
# is not used here for the same reason migration 0022's docstring gives:
# it's unsupported directly on a partitioned table (Postgres requires the
# per-partition CONCURRENTLY-then-ATTACH dance instead), which is a bigger
# undertaking than this migration -- the DROP+CREATE below will briefly
# hold an exclusive lock on this table per partition while rebuilding.
# Acceptable for now given the (relatively fast, index-only) operations
# involved, but flag for the deploy step: run during a lower-traffic window
# if possible, and expect a brief write-blocking pause, not an outage.
_ADD_HASH_COLUMN_SQL = """
    ALTER TABLE extract_tasks
        ADD COLUMN resource_ids_hash INTEGER
        GENERATED ALWAYS AS (hashtext(resource_ids::text)) STORED;
"""

_REBUILD_INDEXES_SQL = """
    DROP INDEX IF EXISTS extract_tasks_fm_po_resources_null_kwargs_idx;
    CREATE UNIQUE INDEX extract_tasks_fm_po_resources_null_kwargs_idx
        ON extract_tasks (dataset_id, fm_id, po_id, resource_ids_hash)
        WHERE kwargs IS NULL;

    DROP INDEX IF EXISTS extract_tasks_fm_po_resources_kwargs_hash_idx;
    CREATE UNIQUE INDEX extract_tasks_fm_po_resources_kwargs_hash_idx
        ON extract_tasks (dataset_id, fm_id, po_id, resource_ids_hash, MD5(kwargs::text))
        WHERE kwargs IS NOT NULL;
"""

_REVERSE_SQL = """
    DROP INDEX IF EXISTS extract_tasks_fm_po_resources_null_kwargs_idx;
    CREATE UNIQUE INDEX extract_tasks_fm_po_resources_null_kwargs_idx
        ON extract_tasks (dataset_id, fm_id, po_id, resource_ids)
        WHERE kwargs IS NULL;

    DROP INDEX IF EXISTS extract_tasks_fm_po_resources_kwargs_hash_idx;
    CREATE UNIQUE INDEX extract_tasks_fm_po_resources_kwargs_hash_idx
        ON extract_tasks (dataset_id, fm_id, po_id, resource_ids, MD5(kwargs::text))
        WHERE kwargs IS NOT NULL;

    ALTER TABLE extract_tasks DROP COLUMN resource_ids_hash;
"""


class Migration(migrations.Migration):
    """
    Adds extract_tasks.resource_ids_hash (a stored generated column,
    hashtext(resource_ids::text)) and rebuilds both resource_ids-keyed
    unique indexes to use it instead of the raw array. resource_ids can be
    up to 12 integers (grouped tasks) vs a fixed 4-byte hash, so this
    shrinks the largest index in the schema (extract_tasks_fm_po_resources_
    null_kwargs_idx was 34% of the table's total footprint at ~62M rows).

    dataset_id/fm_id/po_id stay as plain columns leading both indexes --
    only the expensive variable-length resource_ids array is replaced by
    its hash. This is deliberately NOT the same shape as the original
    extract_tasks_resource_fm_po_kwargs_hash_idx (1.8GB, zero reads across
    the whole incident that started this redesign): that index hashed the
    ENTIRE composite key into one expression, which only Postgres could use
    if the application queried via that exact expression -- nothing did.
    Here, only the array is hashed; ordinary multi-column WHERE clauses on
    dataset_id/fm_id/po_id still work unchanged, and resource_ids_hash is
    just one more column in an otherwise normal composite index.

    Existing plain `resource_ids = [...]` queries (views.py's get-or-create)
    remain CORRECT after this migration without any code change -- Postgres
    still filters resource_ids as a real column, just via a less-selective
    index prefix (dataset_id, fm_id, po_id) followed by a heap recheck,
    rather than an exact index hit. See migration/task after this one for
    the views.py change that restores exact-index-hit performance.
    bulk_create(ignore_conflicts=True) in ingest.py needs no such change --
    Postgres enforces uniqueness at INSERT time via whatever columns back
    the constraint, regardless of how the INSERT was issued.
    """

    dependencies = [
        ("analytics", "0023_extractdata_composite_pk"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_ADD_HASH_COLUMN_SQL,
            reverse_sql=migrations.RunSQL.noop,
            state_operations=[
                migrations.AddField(
                    model_name="extracttask",
                    name="resource_ids_hash",
                    field=models.GeneratedField(
                        expression=Func(
                            Cast("resource_ids", output_field=models.TextField()),
                            function="hashtext",
                        ),
                        output_field=models.IntegerField(),
                        db_persist=True,
                    ),
                ),
            ],
        ),
        migrations.RunSQL(
            sql=_REBUILD_INDEXES_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
```

- [ ] **Step 4: Add tests**

Add to `backend/analytics/tests/test_models.py` (a new test class, following the file's existing conventions):

```python
class ExtractTaskResourceIdsHashTest(TestCase):
    def test_resource_ids_hash_column_exists_and_generated(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT data_type, is_generated FROM information_schema.columns
                WHERE table_name = 'extract_tasks' AND column_name = 'resource_ids_hash'
            """)
            row = cursor.fetchone()
        self.assertIsNotNone(row, "resource_ids_hash column does not exist")
        self.assertEqual(row[0], "integer")
        self.assertEqual(row[1], "ALWAYS")

    def test_resource_ids_hash_matches_hashtext_of_array(self):
        dataset = Dataset.objects.create(name="hashtest", path="hashtest", active=True)
        resource = DatasetResource.objects.create(dataset=dataset, name="r1", path="r1.tif")
        po = ProcessingOption.objects.create(dataset=dataset, short_name="mean", function="rasterstats_default_mean", active=True)
        fc = FeatureCollection.objects.create(name="fc-hash", path="/data/fc-hash", active=True)
        fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape="POINT(0 0)"))

        task = ExtractTask.objects.create(
            dataset_id=dataset.id, resource_ids=[resource.id], fm=fm, po=po,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT hashtext(%s::text)", [[resource.id]])
            expected_hash = cursor.fetchone()[0]

        task.refresh_from_db()
        self.assertEqual(task.resource_ids_hash, expected_hash)

    def test_unique_indexes_use_hash_column(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexdef FROM pg_indexes
                WHERE tablename = 'extract_tasks'
                  AND indexname IN (
                      'extract_tasks_fm_po_resources_null_kwargs_idx',
                      'extract_tasks_fm_po_resources_kwargs_hash_idx'
                  )
            """)
            defs = [row[0] for row in cursor.fetchall()]
        self.assertEqual(len(defs), 2)
        for indexdef in defs:
            self.assertIn("resource_ids_hash", indexdef)
            self.assertNotIn("resource_ids)", indexdef)
```

Add the necessary imports at the top of `test_models.py` if not already present: `from datasets.models import Dataset, DatasetResource`, `from analytics.models import ProcessingOption`, `from features.models import Feature, FeatMap, FeatureCollection` (check existing imports first — some or all may already be there from other test classes in the same file).

- [ ] **Step 5: Measure the size difference against a realistic-scale dataset**

This is a manual verification step, not an automated test (index size differences on a handful of test rows aren't meaningful). Before committing, run this against the scratch Postgres container with a larger synthetic dataset to get real evidence of the size reduction:

```python
# Run via: sudo docker compose run --rm backend uv run python manage.py shell -c "<paste below>"
from django.db import connection
from datasets.models import Dataset, DatasetResource
from analytics.models import ExtractTask, ProcessingOption
from features.models import Feature, FeatMap, FeatureCollection
import random

dataset = Dataset.objects.create(name="sizetest", path="sizetest", active=True)
po = ProcessingOption.objects.create(dataset=dataset, short_name="mean", function="rasterstats_default_mean", active=True)
fc = FeatureCollection.objects.create(name="fc-sizetest", path="/data/fc-sizetest", active=True)
resources = [DatasetResource.objects.create(dataset=dataset, name=f"r{i}", path=f"r{i}.tif") for i in range(20)]
fms = [FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape="POINT(0 0)")) for _ in range(5000)]

ExtractTask.objects.bulk_create([
    ExtractTask(dataset_id=dataset.id, resource_ids=[r.id for r in resources[:12]], fm=fm, po=po)
    for fm in fms
], batch_size=1000)

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT pg_size_pretty(sum(pg_relation_size(child.inhrelid)))
        FROM pg_inherits parent
        JOIN pg_inherits child ON child.inhparent = (
            SELECT indexrelid FROM pg_index WHERE indrelid = 'extract_tasks'::regclass
              AND indexrelid = (SELECT oid FROM pg_class WHERE relname = 'extract_tasks_fm_po_resources_null_kwargs_idx')
        )
        WHERE parent.inhrelid = 'extract_tasks'::regclass
    """)
    print("index size with", ExtractTask.objects.filter(dataset_id=dataset.id).count(), "rows:", cursor.fetchone())
```

Compare this against the same insert volume run on `main` (pre-migration) to get a concrete before/after ratio. Report the actual measured numbers when you commit this task — this is evidence the acceptance criterion "smaller than before" requires, not just a theoretical claim.

- [ ] **Step 6: Run tests**

```
sudo docker compose run --rm backend uv run python manage.py test analytics.tests.test_models analytics.tests.test_build_extract_tasks -v 2
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/0024_extracttask_resource_ids_hash.py backend/analytics/tests/test_models.py
git commit -m "Add extract_tasks.resource_ids_hash generated column, rebuild indexes to use it"
```

---

### Task 2: Update views.py to query via the hash column

**Goal:** `RequestView.post`'s get-or-create loop filters on `resource_ids_hash` in addition to `resource_ids`, so Postgres actually uses the new smaller index for these lookups instead of falling back to a broader index-prefix-plus-heap-recheck scan.

**Files:**
- Modify: `backend/analytics/views.py:217-259` (the get-or-create loop, see exact current text below)
- Modify: `backend/analytics/tests/test_views.py` (the one test that hardcodes exact `.get()`/`.create()` call kwargs)

**Acceptance Criteria:**
- [ ] Both `.get()` calls and the `.create()` call in the get-or-create loop filter/set `resource_ids_hash` alongside `resource_ids`
- [ ] The hash value passed is computed server-side by Postgres (via a raw SQL expression), not replicated in Python — avoiding any risk of a Python/Postgres hash mismatch silently breaking lookups
- [ ] `EXPLAIN` on the `.get()` query (verified manually, see Step 3) shows an index scan using `extract_tasks_fm_po_resources_null_kwargs_idx` with all four columns as index conditions, not just a 3-column prefix
- [ ] `test_integrity_error_on_create_falls_back_to_get` in `test_views.py` is updated to match the new call signature and still passes
- [ ] All other existing tests in `test_views.py` and `test_ingest.py` pass unmodified (`ingest.py` itself needs no code change, per Task 1's migration docstring — this task's job is only to verify that remains true)

**Verify:** `sudo docker compose run --rm backend uv run python manage.py test analytics.tests.test_views analytics.tests.test_ingest -v 2` → all pass

**Steps:**

- [ ] **Step 1: Read current code**

Read `backend/analytics/views.py:217-259` in full (current text, may have drifted — re-read the live file):

```python
            # The functional unique indexes (migration 0022) are:
            #   (dataset_id, fm_id, po_id, resource_ids) WHERE kwargs IS NULL
            #   (dataset_id, fm_id, po_id, resource_ids, MD5(kwargs::text))
            #       WHERE kwargs IS NOT NULL
            # Django JSONField maps None to JSON null for equality queries, but
            # rows with no kwargs (e.g. from build_extract_tasks) have SQL NULL.
            # Use isnull lookup for the None case so the GET matches SQL NULL rows.
            if task_kwargs is None:
                kwargs_lookup = {"kwargs__isnull": True}
            else:
                kwargs_lookup = {"kwargs": task_kwargs}

            task_ids = []
            for fm in fms:
                for resource in resource_list:
                    for po in pos:
                        try:
                            task = ExtractTask.objects.get(
                                dataset_id=dataset_obj.id,
                                resource_ids=[resource.id],
                                fm=fm,
                                po=po,
                                **kwargs_lookup,
                            )
                        except ExtractTask.DoesNotExist:
                            try:
                                task = ExtractTask.objects.create(
                                    dataset_id=dataset_obj.id,
                                    resource_ids=[resource.id],
                                    fm=fm,
                                    po=po,
                                    kwargs=task_kwargs,
                                )
                            except IntegrityError:
                                task = ExtractTask.objects.get(
                                    dataset_id=dataset_obj.id,
                                    resource_ids=[resource.id],
                                    fm=fm,
                                    po=po,
                                    **kwargs_lookup,
                                )
                        if task.priority < 1:
                            task.priority = 1
                            task.save(update_fields=["priority"])
                        task_ids.append(task.id)

            all_task_ids.update({tid: dataset_obj.id for tid in task_ids})
```

- [ ] **Step 2: Add the hash filter**

Replace this block with:

```python
            # The functional unique indexes (migration 0024) are:
            #   (dataset_id, fm_id, po_id, resource_ids_hash) WHERE kwargs IS NULL
            #   (dataset_id, fm_id, po_id, resource_ids_hash, MD5(kwargs::text))
            #       WHERE kwargs IS NOT NULL
            # resource_ids_hash is a stored generated column (hashtext(resource_ids
            # ::text)) -- filtering on it directly lets Postgres use an exact index
            # hit on all four columns instead of a 3-column prefix (dataset_id,
            # fm_id, po_id) followed by a heap recheck of resource_ids. Still also
            # filter on resource_ids itself (not just the hash) so a hash collision
            # -- vanishingly unlikely, but hashtext() is a 32-bit hash -- can never
            # return the wrong row; the hash is purely an index-selectivity
            # optimization; resource_ids remains the actual correctness check.
            # Django JSONField maps None to JSON null for equality queries, but
            # rows with no kwargs (e.g. from build_extract_tasks) have SQL NULL.
            # Use isnull lookup for the None case so the GET matches SQL NULL rows.
            if task_kwargs is None:
                kwargs_lookup = {"kwargs__isnull": True}
            else:
                kwargs_lookup = {"kwargs": task_kwargs}

            task_ids = []
            for fm in fms:
                for resource in resource_list:
                    for po in pos:
                        resource_ids = [resource.id]
                        resource_ids_hash = RawSQL("hashtext(%s::text)", [resource_ids])
                        try:
                            task = ExtractTask.objects.get(
                                dataset_id=dataset_obj.id,
                                resource_ids=resource_ids,
                                resource_ids_hash=resource_ids_hash,
                                fm=fm,
                                po=po,
                                **kwargs_lookup,
                            )
                        except ExtractTask.DoesNotExist:
                            try:
                                task = ExtractTask.objects.create(
                                    dataset_id=dataset_obj.id,
                                    resource_ids=resource_ids,
                                    fm=fm,
                                    po=po,
                                    kwargs=task_kwargs,
                                )
                            except IntegrityError:
                                task = ExtractTask.objects.get(
                                    dataset_id=dataset_obj.id,
                                    resource_ids=resource_ids,
                                    resource_ids_hash=resource_ids_hash,
                                    fm=fm,
                                    po=po,
                                    **kwargs_lookup,
                                )
                        if task.priority < 1:
                            task.priority = 1
                            task.save(update_fields=["priority"])
                        task_ids.append(task.id)

            all_task_ids.update({tid: dataset_obj.id for tid in task_ids})
```

Note `.create()` does NOT need the hash filter — `resource_ids_hash` is a generated column, Postgres computes it automatically on INSERT from whatever `resource_ids` is set to; explicitly setting it would actually raise an error (generated columns reject explicit values on INSERT).

Add the import at the top of `backend/analytics/views.py`:

```python
from django.db.models.expressions import RawSQL
```

**Before finalizing**, verify `RawSQL("hashtext(%s::text)", [resource_ids])` actually produces a query filter Postgres can push down correctly — test this against the real scratch database (not just unit-test mocks) as part of Step 4, since `RawSQL` with an array parameter passed through Django's query compiler has a real chance of not matching Postgres's own `resource_ids::text` cast representation exactly (e.g. array literal formatting differences). If it doesn't match, the `.get()` would raise `DoesNotExist` even for a row that actually exists — a correctness bug, not just a missed optimization, so this needs to be verified with a real integration test against real data, not assumed.

- [ ] **Step 3: Verify the index is actually used**

Manually confirm via `EXPLAIN` against the scratch database (not part of the automated test suite, a one-off verification):

```
sudo docker compose run --rm backend uv run python manage.py shell -c "
from django.db import connection
from analytics.models import ExtractTask
qs = ExtractTask.objects.filter(dataset_id=1, resource_ids=[1], resource_ids_hash=1, fm_id=1, po_id=1, kwargs__isnull=True)
print(qs.explain())
"
```

Confirm the output mentions `extract_tasks_fm_po_resources_null_kwargs_idx` as an `Index Scan`/`Index Only Scan`, not a `Seq Scan`.

- [ ] **Step 4: Update the affected test**

In `backend/analytics/tests/test_views.py`, find `test_integrity_error_on_create_falls_back_to_get` (currently around lines 118-168). Update the `expected_get_kwargs` dict and the `mock_create.assert_called_once_with(...)` call to account for the new `resource_ids_hash` argument on the `.get()` calls (NOT on `.create()`, per Step 2's note above). Read the test's current full text first, then adjust only the kwargs-matching assertions — the test's overall structure (mocking `.get`/`.create`, forcing an `IntegrityError`, asserting the fallback `.get()` fires) stays the same.

Since `resource_ids_hash` is passed as a `RawSQL(...)` expression object (not a plain value), the mock assertion needs to compare against an equivalent `RawSQL` instance or use a more targeted assertion (e.g. checking the call's `resource_ids`/`dataset_id`/`fm`/`po`/`kwargs__isnull` kwargs individually via `call.kwargs["resource_ids"]` etc., rather than a single dict-equality `assert_called_once_with`, since `RawSQL` objects may not compare equal via `==` even with identical SQL/params — verify this empirically and adjust the assertion style if a direct equality comparison doesn't work cleanly).

- [ ] **Step 5: Run tests**

```
sudo docker compose run --rm backend uv run python manage.py test analytics.tests.test_views analytics.tests.test_ingest -v 2
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/views.py backend/analytics/tests/test_views.py
git commit -m "Filter get-or-create lookups on resource_ids_hash for index selectivity"
```

---

### Task 3: Deploy

**USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Goal:** Ship both schema changes to production via the existing CI/CD pipeline, with explicit attention to the fact that (unlike the original redesign's wipe-first deploy) both migrations run against live, non-empty, actively-written-to tables.

**Files:** none (deploy-only task)

**Acceptance Criteria:**
- [ ] Migrations 0023 and 0024 apply cleanly against production via the `geoquery-db-migration` Job
- [ ] `extract_data` confirmed to have no `id` column and the correct composite PK in production (`information_schema` query against the live DB, not just the migration succeeding silently)
- [ ] `extract_tasks_fm_po_resources_null_kwargs_idx` and `extract_tasks_fm_po_resources_kwargs_hash_idx` confirmed rebuilt on `resource_ids_hash` in production
- [ ] Real index size reduction measured and reported (before/after `pg_total_relation_size` comparison against production's actual current index sizes, not the synthetic test from Task 1 Step 5)
- [ ] A real on-demand request submission (through `RequestView.post`, the actual get-or-create path) succeeds end-to-end post-deploy, proving the `resource_ids_hash` filter change didn't break real lookups
- [ ] `processing-worker`/`background-worker`/`geoquery-import` pods continue writing to `extract_data` without errors post-deploy (spot-check logs for a few minutes after the migration completes, given real production writes are continuous)

**Verify:** `kubectl logs -n geoquery-prod job/geoquery-db-migration` shows success; direct `information_schema`/`pg_indexes` queries against the live DB (via `kubectl cnpg psql`) confirm both schema changes; no new errors in `processing-worker`/`background-worker` logs in the minutes following deploy

**Steps:**

- [ ] **Step 1: Pre-deploy sanity check**

Before merging, re-confirm production's current `extract_data` row count and `name`-nullability are still consistent with this plan's assumptions (they may have grown/changed since this plan was written, given continuous live writes):

```sql
SELECT count(*) FROM extract_data WHERE name IS NULL;
SELECT dataset_id, extract_task_id, name, count(*) FROM extract_data GROUP BY dataset_id, extract_task_id, name HAVING count(*) > 1 LIMIT 5;
```

Both must still return 0 rows before proceeding. If either has any rows, STOP and investigate — do not proceed with the migration until root-caused, since it would mean the composite PK is not actually a valid constraint against current production data.

- [ ] **Step 2: Open a PR, merge, and deploy**

Follow the same `[DEPLOY-X.Y.Z]` commit-marker flow used for the original extract-tasks-redesign deploy. Given the SHA-resolution race fixed in PR #17 (this branch's `deploy.yml` already has that fix on `main`), a single correctly-versioned deploy attempt should now resolve the right image on the first try — but confirm the resolved `BACKEND_SHA` in the deploy workflow's logs matches the actual merge commit before letting the migration job run, the same way that was checked after the fix.

- [ ] **Step 3: Verify against the live database**

```sql
-- extract_data composite PK
SELECT kcu.column_name FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name AND kcu.table_name = tc.table_name
WHERE tc.table_name = 'extract_data' AND tc.constraint_type = 'PRIMARY KEY' ORDER BY kcu.ordinal_position;
-- expect: dataset_id, extract_task_id, name

SELECT count(*) FROM information_schema.columns WHERE table_name = 'extract_data' AND column_name = 'id';
-- expect: 0

-- extract_tasks hashed indexes
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'extract_tasks'
  AND indexname IN ('extract_tasks_fm_po_resources_null_kwargs_idx', 'extract_tasks_fm_po_resources_kwargs_hash_idx');
-- expect: both mention resource_ids_hash, neither mentions bare "resource_ids)"
```

- [ ] **Step 4: Measure real size reduction**

Record `extract_tasks_fm_po_resources_null_kwargs_idx`'s size immediately before and after this deploy (aggregated across all partitions, same query pattern used earlier in this project: sum `pg_relation_size` over `pg_inherits` children of the logical index). Report the actual before/after numbers — this is the deliverable the whole plan exists to produce, so the real measured reduction (not just "it should be smaller") is the closing evidence.

- [ ] **Step 5: End-to-end request submission check**

Submit a real request through the actual API (or via `manage.py shell` calling the same code path) for a small, known dataset, and confirm a `RequestMap`/`ExtractTask` row gets created correctly and the request completes normally. This proves the `resource_ids_hash` filter in `views.py` works against real production data, not just the scratch test database.

- [ ] **Step 6: Monitor for errors**

Watch `processing-worker` and `background-worker` pod logs for a few minutes following the deploy, confirming no new errors appear related to `ExtractData` saves or `ExtractTask` get-or-create lookups (both code paths this plan touched).
