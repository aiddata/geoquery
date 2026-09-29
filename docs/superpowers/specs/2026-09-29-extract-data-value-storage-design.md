# Extract Data Value Storage — Design

## Problem

Since the monthly task aggregation work, `extract_data` stores every value as
an array, position-aligned with the owning task's `resource_ids`. Three typed
array columns already exist (`float_values FLOAT8[]`, `int_values BIGINT[]`,
`str_values VARCHAR(100)[]`) with a `data_column VARCHAR(100)` discriminator
naming which one is in use.

A scan of all 713,667,210 production rows on 2026-09-29 found:

| column | rows | share | max array length |
|---|---|---|---|
| `int_values` | 437,253,101 | 61.3% | **1** |
| `str_values` | 210,329,319 | 29.5% | **1** |
| `float_values` | 66,084,790 | 9.3% | **1** |
| multi-element arrays | **0** | **0%** | — |

Not one array in the database holds more than a single element. The array
machinery is currently pure overhead: measured on real rows, a 1-element array
occupies ~29 of ~70 data bytes — roughly 41% of the row — to carry one 8-byte
number that a scalar column would store in 8.

### `'None'` is not a value

All 210,329,319 `str_values` rows contain exactly `['None']`. There is no other
string anywhere in the column; `str_values` is not storing string data at all,
only a nodata sentinel.

It originates in `_classify_value` (`analytics/tasks/processing.py`), whose
fallthrough branch stringifies anything that is not `int`/`float`/`str`:

```python
else:
    return "str", str(value)
```

`rasterstats` returns `None` for a feature with no valid pixels, so
`str(None)` produces the literal text `'None'`.

**This reaches users.** No filtering exists anywhere downstream. In
`analytics/tasks/merge.py` the guard is `values[i] is None`, which the *string*
`'None'` passes, and `coerce = str` then writes the text `None` into the
merged CSV. 29.5% of all extract data is affected. This is a correctness
defect, not only a storage inefficiency.

### Element-level NULL is overloaded

`ExtractData`'s docstring defines an element-level NULL as "position `i` still
needs (re)processing". Two code paths depend on that meaning:

- `_positions_needing_processing` uses array NULLs to decide what a retry
  re-runs.
- `_run_extract_task` scans array NULLs to decide whether the task may move to
  `status=1`.

This is precisely why the `'None'` string exists and cannot simply be replaced
with SQL NULL: a genuinely-nodata position stored as NULL would be re-processed
forever and its task would never complete.

### A latent type-misfiling bug

`data_column` is fixed from the **first** value seen:

```python
data_column, _ = _classify_value(next(iter(values_by_pos.values())))
```

If that first value is `None`, the row is typed `'str'` permanently and every
later real value is coerced into the varchar array. Today this is masked
because every array has exactly one element, so no mixing is possible.

It stops being masked imminently. Of the 2,752 rows in
`extract_task_build_progress`, **930 have `cardinality(resource_ids) = 12`**
(the year-grouped monthly datasets: 3, 21, 22, 44, 71) and **all 930 are
`never_started`**. The moment they build, a January nodata will silently
stringify the other eleven months.

### Why one row per task holds

Two facts make the design tractable:

- `po` determines `name`. The four-stat datasets are four separate
  `processing_options` rows (po 8=`mean`, 9=`max`, 10=`min`, 11=`count`), not
  four `extract_data` rows. One task produces one row.
- The categorical processor fills absent categories with `0`, never `None`
  (`zonal_stats_rasterstats.rasterstats_default_categorical`). Partitions
  `ds_1` and `ds_2` are 100% `int_values` with zero nodata.

So every one of the 210.3M nodata rows is a task whose single result was
nodata. There is no partially-nodata case to reason about.

## Approach

Add scalar columns beside the arrays, make nodata a real SQL NULL, move
completeness off array contents, and discard the existing rows rather than
migrating them.

### Target schema

```sql
extract_task_id  integer      NOT NULL
dataset_id       integer      NOT NULL
name             varchar(100) NOT NULL

int_value        bigint             -- cardinality(resource_ids) = 1
float_value      double precision
str_value        varchar(100)

int_values       bigint[]           -- cardinality(resource_ids) > 1
float_values     double precision[]
str_values       varchar(100)[]

PRIMARY KEY (dataset_id, extract_task_id, name)
```

A row populates one side or the other. Unused columns cost only a null-bitmap
bit in PostgreSQL, so the unused side is free.

`data_column` is **dropped**. With six typed columns the type is implied by
which one is non-NULL, and nothing needs the type of a NULL value — both
readers skip NULLs regardless of type. Saves ~4–6 bytes per row.

Measured heap today is ~87 bytes per row (58 GB across 713.7M rows). Expected
after: ~48 bytes for a single-value row, ~160 for a grouped 12-element one.

### Nodata representation

A task whose every result is nodata writes a row with all six value columns
NULL. The row's existence is the record that the work was done; its NULLs are
the record that there was nothing to find.

The alternative — writing no row and marking the task with a distinct status —
saves roughly twice as much but was rejected. It requires every consumer to
infer nodata from absence, it moves semantics that five call sites depend on
(`manage_user_requests.py:698` and `:708`, `mcp_server/tools/catalog.py:319`,
`stats/builder.py:83` and `:97`), and a missed call site fails silently — a
request would wait indefinitely on tasks it believes unfinished. It would also
make a name that is nodata for every feature vanish from merged output
entirely rather than appear as an empty column.

### Completeness

Both array-NULL dependencies are removed.

`_positions_needing_processing` becomes unconditional — it returns
`set(range(n))` whenever the task is not complete. A task completes if and only
if its run raised nothing. Because every position is recomputed on a retry, the
row is replaced wholesale rather than merged.

The cost is that a 12-resource task which failed on one month re-extracts all
twelve. This is free for the 1,822 single-value pairs (one position, nothing to
skip) and is only paid by the 930 grouped pairs, and only when they actually
fail. Per-position tracking (an `attempted` bitmask) was considered and
rejected as unnecessary complexity for that narrow case.

`_positions_needing_processing` is kept as a function rather than inlined,
specifically to carry a docstring explaining why the skip-already-successful
optimization was removed — so it is not reinstated without re-breaking the
NULL semantics.

## Components

### `analytics/tasks/processing.py`

`_classify_value` returns `None` for nodata rather than stringifying it:

```python
def _classify_value(value):
    """Return (column, coerced), or None when the value is nodata.

    None means nodata and becomes SQL NULL -- never the string 'None'.
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

Column selection uses the **first non-None** value rather than the first value,
which fixes the misfiling bug above: nodata can no longer determine a row's
type. A later value whose type conflicts is still coerced, matching today's
behaviour, but now logs a warning rather than failing silently.

Row shape follows `n = len(resource_ids)`: `n == 1` writes the scalar column,
`n > 1` writes the array position-aligned.

The `null_positions` scan in `_run_extract_task` is deleted.

### `analytics/models.py`

`ExtractData` gains `int_value`, `float_value`, `str_value`; loses
`data_column`. The class docstring's "Two independent levels of NULL" section
is rewritten: element-level NULL now means *nodata*, and "needs reprocessing"
is no longer expressible in the row — it is a property of the task's status.

### `analytics/tasks/merge.py`

The `data_column` branch (lines 225–243) becomes "whichever of the six columns
is non-NULL": scalar yields one value at position 0, array stays
position-aligned. The existing `values[i] is None → continue` guard is
preserved unchanged, so a NULL becomes a genuine NaN in the assembled
DataFrame. This is where `"None"` stops reaching user downloads.

### `visualize/data.py`

Both `_REQUEST_EXTRACT_DATA_SQL` and `_EXPLORE_EXTRACT_DATA_SQL` unnest the
three arrays in parallel with `resource_ids`. Scalar rows have NULL arrays and
would unnest to nothing, dropping the row entirely, so the lateral must cover
both shapes:

```sql
CROSS JOIN LATERAL unnest(
    et.resource_ids,
    COALESCE(ed.float_values, ARRAY[ed.float_value]),
    COALESCE(ed.int_values,   ARRAY[ed.int_value]),
    COALESCE(ed.str_values,   ARRAY[ed.str_value])
) WITH ORDINALITY AS u(resource_id, float_value, int_value, str_value, ord)
```

`ed.data_column` is removed from both SELECT lists; the Python loop branches on
which value is non-NULL instead.

## Cutover

The existing 713.7M rows are discarded rather than migrated. `extract_data` is
fully derived from rasters and boundaries, so it is regenerable by definition.
The discard is also a minority of the eventual dataset: 347.4M of 2.63B target
tasks have been processed, so roughly 87% of the extract data this system will
hold has not been produced yet and is unaffected.

User-facing exposure is eight requests total (five complete with output files
already written, one in flight, two failed).

**Ordering is load-bearing.** The writer changes must deploy before the
truncate. Reversed, the rebuild regenerates 347M rows with `'None'` all over
again.

1. Deploy schema, writers, readers. Additive and backward compatible: the new
   columns are empty and the old readers still work against existing arrays.
2. `TRUNCATE extract_data;` — instant, reclaims 115 GB. No cascade needed; the
   FK points from `extract_data` to `extract_tasks`, not the reverse.
3. Reset tasks to pending, **one partition at a time with a VACUUM between**:

   ```sql
   UPDATE extract_tasks_ds_N
   SET status = 0, complete_time = NULL, attempts = 0, error = NULL
   WHERE status <> 0;
   ```

The reset is the expensive half: 347M rows rewritten is ~48 GB of dead heap,
and the pending partial index grows from 258.9M to 606M entries (24 GB →
~56 GB). That ~80 GB transient is covered by the 115 GB the truncate just
freed, but only if sequenced per-partition rather than run as one statement.

Re-processing 347,359,371 tasks costs roughly 245 hours (~10 days) at the
measured 1.42M tasks/hr, competing with a builder that needs ~56 days to finish
supplying new work.

### Accepted losses

`stats/builder.py:83` builds the *extract task completions over time* chart
from `complete_time WHERE status=1`. The reset destroys that history
permanently — it records when work happened and cannot be regenerated. Accepted
rather than snapshotting it.

The MCP catalog's coverage percentages (`mcp_server/tools/catalog.py:319`) drop
to near-zero until re-processing catches up. Self-healing, no action needed.

## Testing

- `_classify_value(None)` returns `None`; a nodata result stores SQL NULL and
  never the string `'None'`.
- Scalar path at `n=1` writes `*_value` and leaves `*_values` NULL; grouped path
  at `n>1` does the reverse.
- Column selection uses the first non-None value: a leading nodata followed by
  floats produces a `float` row, not a `str` row. This is the regression test
  for the misfiling bug.
- A task whose every result is nodata reaches `status=1` rather than looping,
  and writes one row with all value columns NULL.
- A retry recomputes every position and replaces the row wholesale.
- Merge-level: a nodata result produces an empty cell in the output, not the
  text `None`.

## Out of scope

- `max_wal_size` / checkpoint tuning. Measured on 2026-09-29 at 423 of 502
  checkpoints fired by `max_wal_size` and 89% of wall clock in checkpoint
  writes, but it is independent config work and deliberately sequenced after
  this.
- The builder run-lock fan-out decay (workers that exit are never replaced
  because survivors keep the heartbeat fresh).
- Preserving the /stats completion history.
