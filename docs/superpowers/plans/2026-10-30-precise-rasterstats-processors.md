# Precise Rasterstats Processors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `rasterstats_precise_mean`, `rasterstats_precise_sum` and `rasterstats_precise_count` processors (single-feature and batch forms) that use the rasterstats fork's percent-cover weighting, plus latitude correction for mean.

**Architecture:** Thin wrappers over the existing `_rasterstats_default` / `_batch_default` helpers in `backend/analytics/processors/zonal_stats_rasterstats.py`. A `_precise_kwargs(stat, kwargs)` helper layers precise defaults (`percent_cover_weighting=True`, `percent_cover_scale=10`, `limit=1_000_000`, plus `latitude_correction=True` for mean) under the caller's kwargs, so processing option/task kwargs override them. The functions are registered in `REGISTRY`; the batch forms go into `BATCH` and so into `BATCH_REGISTRY`.

**Tech Stack:** Django (SimpleTestCase), rasterstats fork `aiddata/geoquery-python-rasterstats@85f58864c5f78b4c4cd314e92a4e141c693d6dc0`, shapely, numpy, rasterio.

**User decisions (already made):**
- Precise versions of mean, sum and count ("mean + sum + count").
- precise_mean = latitude correction + percent-cover weighting; precise_sum and precise_count = percent-cover weighting only.
- Memory bounded by defaults in code (scale=10, limit=1,000,000) that processing option kwargs can override ("Defaults in code, overridable").
- New registered functions with batch forms ("A: new registered funcs").
- GeoQuery processors only; adding precise options to datasets in geo-datasets is a follow-up.
- Spec: `docs/superpowers/specs/2026-10-30-precise-rasterstats-processors-design.md` (approved).

**Repository rule:** Do not commit, push, or deploy. The user's global instructions forbid it without explicit permission. Each task ends by leaving changes uncommitted and reporting them.

---

## Background facts the engineer needs

- Processors are called as `func(feat, raster_path, name=..., **kwargs)` with a **shapely geometry** and return `[(name, value)]`. Batch forms are `batch(feats, raster_path, name=..., **kwargs)` and yield `(index, result_or_exception)`.
- `_rasterstats_kwargs` fills in `all_touched=True` and `nodata=None` only when the caller didn't pass them. `name` passes through to `zonal_stats` harmlessly, because the fork accepts `**kwargs`.
- Measured with the fork at 85f5886 (these are the test expectations):
  - 10×10 raster spanning (0,0)–(10,10) with values `arange(100)` (row 0 at the top, so the bottom row holds 90..99). For `box(0, 0, 1.5, 1)`: precise count `1.5`, precise sum `135.5`, precise mean `≈ 90.3333`. Default count `2`, default sum `181.0`.
  - The same values on bounds (0,60)–(10,70), column `box(0, 60, 1, 70)`: default mean `45.0`; precise mean `≈ 48.08945` (southern rows have more area and hold the larger values); precise mean with `latitude_correction=False` is `45.0`; precise sum `450.0` equals the default sum (sum is not latitude-corrected).
  - `box(0, 0, 1.25, 1)`: precise count `≈ 1.3` at scale 10 (`1.2999999523…`, float32 coverage) and exactly `1.25` with `percent_cover_scale=4`.
  - `Point(0.5, 0.5)`: the fork disables percent cover for points, so precise count is `1`, the same as default.
  - Polygon `[(0.33,60.21),(9.61,61.13),(8.77,69.43),(1.27,68.81)]` on the high-latitude raster with `limit=9` splits into 16 tiles, and the precise mean/sum/count agree with the unsplit results within 1e-8 relative.
- The fork warns (UserWarning) if `all_touched` is False with percent cover, or if `percent_cover_scale` is missing. The defaults avoid both.
- `rasterstats.io.NodataWarning` fires for rasters without a nodata value when `nodata=None`. That's existing behavior for the default processors too, so the tests don't assert on warnings.

## File structure

- Modify `backend/analytics/processors/zonal_stats_rasterstats.py`: add a precise section (defaults, `_precise_kwargs`, three public functions) after `rasterstats_default_categorical`; add `_batch_precise` after `rasterstats_default_categorical_batch`; add three `BATCH` entries.
- Modify `backend/analytics/processors/__init__.py`: import and register the three functions.
- Create `backend/analytics/tests/test_precise_processors.py`: behavior tests.
- `backend/analytics/tests/test_batch_processors.py`: unchanged. Its registry-coverage and batch-equals-single tests pick up the new processors automatically.

---

### Task 1: Precise processors with batch forms and registration

**Goal:** `REGISTRY` and `BATCH_REGISTRY` expose `rasterstats_precise_mean/sum/count` with coverage-weighted (and, for mean, latitude-corrected) results whose defaults the caller's kwargs can override.

**Files:**
- Create: `backend/analytics/tests/test_precise_processors.py`
- Modify: `backend/analytics/processors/zonal_stats_rasterstats.py` (insert after line 68, the end of `rasterstats_default_categorical`; insert after `rasterstats_default_categorical_batch`, before `BATCH = {`; extend `BATCH`)
- Modify: `backend/analytics/processors/__init__.py` (import block lines 25-33, `REGISTRY` tuple)

**Acceptance Criteria:**
- [ ] `box(0,0,1.5,1)` on the equator raster: precise count `== 1.5`, precise sum `== 135.5`, precise mean `≈ 90.3333` (5 places)
- [ ] High-latitude column: precise mean `≈ 48.08945` (4 places) and greater than the default mean `45.0`; precise sum `== 450.0` equals the default sum
- [ ] `latitude_correction=False` makes precise mean `45.0`; `percent_cover_scale=4` makes `box(0,0,1.25,1)` precise count exactly `1.25`
- [ ] Point geometry: precise count `== 1`
- [ ] `limit=9` splits the test polygon into more than one tile, and the results match the unsplit ones with `rtol=1e-6`
- [ ] `test_batch_processors` passes, including the registry-coverage and batch-equals-single checks for the new names

**Verify:** `cd /home/userx/git/geoquery/backend && env DJANGO_SECRET_KEY=test-only-key DEBUG=True uv run python manage.py test analytics.tests.test_precise_processors analytics.tests.test_batch_processors -v 2` → all tests `ok`, `OK` at the end

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `backend/analytics/tests/test_precise_processors.py`:

```python
"""Precise rasterstats processors weight pixels by coverage and latitude."""

from unittest import mock

import numpy as np
import rasterstats.main
import shapely
from django.test import SimpleTestCase

from analytics.processors import REGISTRY
from analytics.tests.extract_helpers import raster_dir, write_raster


class PreciseProcessorTests(SimpleTestCase):
    def setUp(self):
        self.tmp = raster_dir()
        self.addCleanup(self.tmp.cleanup)
        # row 0 is the top (north) row, so the bottom row holds 90..99
        values = np.arange(100, dtype="float64").reshape(10, 10)
        self.raster = write_raster(self.tmp.name, "r.tif", values)
        self.high_lat = write_raster(self.tmp.name, "hl.tif", values, bounds=(0, 60, 10, 70))

    def value(self, function, feat, raster, **kwargs):
        [(column, value)] = REGISTRY[function](feat, raster, name="v", **kwargs)
        self.assertEqual(column, "v")
        return value

    def test_partial_pixels_are_weighted_by_coverage(self):
        # covers pixel 90 fully and pixel 91 half
        feat = shapely.box(0, 0, 1.5, 1)
        self.assertEqual(self.value("rasterstats_precise_count", feat, self.raster), 1.5)
        self.assertEqual(self.value("rasterstats_precise_sum", feat, self.raster), 135.5)
        self.assertAlmostEqual(
            self.value("rasterstats_precise_mean", feat, self.raster), 90.33333, places=5
        )
        # the default processors count both touched pixels in full
        self.assertEqual(self.value("rasterstats_default_count", feat, self.raster), 2)
        self.assertEqual(self.value("rasterstats_default_sum", feat, self.raster), 181.0)

    def test_mean_is_latitude_corrected_but_sum_is_not(self):
        # a full column: southern rows cover more area and hold larger values
        column = shapely.box(0, 60, 1, 70)
        default_mean = self.value("rasterstats_default_mean", column, self.high_lat)
        precise_mean = self.value("rasterstats_precise_mean", column, self.high_lat)
        self.assertEqual(default_mean, 45.0)
        self.assertGreater(precise_mean, default_mean)
        self.assertAlmostEqual(precise_mean, 48.08945, places=4)
        self.assertEqual(
            self.value("rasterstats_precise_sum", column, self.high_lat),
            self.value("rasterstats_default_sum", column, self.high_lat),
        )

    def test_kwargs_override_the_defaults(self):
        column = shapely.box(0, 60, 1, 70)
        self.assertEqual(
            self.value("rasterstats_precise_mean", column, self.high_lat, latitude_correction=False),
            45.0,
        )
        feat = shapely.box(0, 0, 1.25, 1)
        self.assertAlmostEqual(
            self.value("rasterstats_precise_count", feat, self.raster), 1.3, places=5
        )
        self.assertEqual(
            self.value("rasterstats_precise_count", feat, self.raster, percent_cover_scale=4), 1.25
        )

    def test_points_count_whole_pixels(self):
        # the fork disables percent cover for points
        point = shapely.Point(0.5, 0.5)
        self.assertEqual(self.value("rasterstats_precise_count", point, self.raster), 1)

    def test_split_features_match_unsplit_results(self):
        feat = shapely.Polygon([(0.33, 60.21), (9.61, 61.13), (8.77, 69.43), (1.27, 68.81)])
        real_split = rasterstats.main.split_geom
        tiles = []

        def recording_split(*args, **kwargs):
            pieces = list(real_split(*args, **kwargs))
            tiles.append(len(pieces))
            return pieces

        for function in (
            "rasterstats_precise_mean", "rasterstats_precise_sum", "rasterstats_precise_count"
        ):
            with self.subTest(processor=function):
                whole = self.value(function, feat, self.high_lat)
                tiles.clear()
                with mock.patch.object(rasterstats.main, "split_geom", side_effect=recording_split):
                    split = self.value(function, feat, self.high_lat, limit=9)
                self.assertGreater(tiles[0], 1)
                np.testing.assert_allclose(split, whole, rtol=1e-6)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/userx/git/geoquery/backend && env DJANGO_SECRET_KEY=test-only-key DEBUG=True uv run python manage.py test analytics.tests.test_precise_processors -v 2`
Expected: every test errors with `KeyError: 'rasterstats_precise_count'` (or `_mean`/`_sum`)

- [ ] **Step 3: Add the single-feature precise processors**

In `backend/analytics/processors/zonal_stats_rasterstats.py`, insert after `rasterstats_default_categorical` (which ends with `return _categorical_output(stats[0], kwargs)`), before the `# --- batch forms ---` comment:

```python
# --- precise forms -----------------------------------------------------------
#
# Area-aware statistics from the AidData rasterstats fork. Each pixel is
# weighted by the fraction of it the feature covers (percent cover), and mean
# also weights each pixel row by its true area at that latitude, which assumes
# an EPSG:4326 raster. Percent cover rasterizes every window at scale x scale
# sub-pixels, so `limit` splits large features into tiles of at most that many
# source pixels (~200 MB peak per tile at these defaults). Processing option
# and task kwargs override any default here. Point features get no percent
# cover (the fork disables it), and precise count is a float.

_PRECISE_DEFAULTS = {
    "percent_cover_weighting": True,
    "percent_cover_scale": 10,
    "limit": 1_000_000,
}
_PRECISE_STAT_DEFAULTS = {"mean": {"latitude_correction": True}}


def _precise_kwargs(stat, kwargs):
    return {**_PRECISE_DEFAULTS, **_PRECISE_STAT_DEFAULTS.get(stat, {}), **kwargs}


def rasterstats_precise_mean(feat, raster, **kwargs):
    return _rasterstats_default(feat, raster, "mean", **_precise_kwargs("mean", kwargs))


def rasterstats_precise_sum(feat, raster, **kwargs):
    return _rasterstats_default(feat, raster, "sum", **_precise_kwargs("sum", kwargs))


def rasterstats_precise_count(feat, raster, **kwargs):
    return _rasterstats_default(feat, raster, "count", **_precise_kwargs("count", kwargs))
```

- [ ] **Step 4: Add the batch forms**

In the same file, insert after `rasterstats_default_categorical_batch` and before `BATCH = {`:

```python
def _batch_precise(stat):
    default = _batch_default(stat)

    def batch(feats, raster, **kwargs):
        return default(feats, raster, **_precise_kwargs(stat, kwargs))

    batch.__name__ = f"rasterstats_precise_{stat}_batch"
    return batch
```

Then add these three entries at the end of the `BATCH` dict, after `"rasterstats_default_categorical": rasterstats_default_categorical_batch,`:

```python
    "rasterstats_precise_mean": _batch_precise("mean"),
    "rasterstats_precise_sum": _batch_precise("sum"),
    "rasterstats_precise_count": _batch_precise("count"),
```

- [ ] **Step 5: Register the functions**

In `backend/analytics/processors/__init__.py`, replace the import block:

```python
from analytics.processors.zonal_stats_rasterstats import (
    BATCH,
    rasterstats_default_categorical,
    rasterstats_default_count,
    rasterstats_default_max,
    rasterstats_default_mean,
    rasterstats_default_min,
    rasterstats_default_sum,
)
```

with:

```python
from analytics.processors.zonal_stats_rasterstats import (
    BATCH,
    rasterstats_default_categorical,
    rasterstats_default_count,
    rasterstats_default_max,
    rasterstats_default_mean,
    rasterstats_default_min,
    rasterstats_default_sum,
    rasterstats_precise_count,
    rasterstats_precise_mean,
    rasterstats_precise_sum,
)
```

and in the `REGISTRY` tuple, after `rasterstats_default_categorical,` add:

```python
        rasterstats_precise_mean,
        rasterstats_precise_sum,
        rasterstats_precise_count,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /home/userx/git/geoquery/backend && env DJANGO_SECRET_KEY=test-only-key DEBUG=True uv run python manage.py test analytics.tests.test_precise_processors analytics.tests.test_batch_processors -v 2`
Expected: all tests `ok`, including `test_every_rasterstats_processor_has_a_batch_form` and `test_batch_results_equal_single_feature_results` (whose subtests now include the three `rasterstats_precise_*` names); final line `OK`.

- [ ] **Step 7: Leave uncommitted and report**

Run `git -C /home/userx/git/geoquery status -s`. Expect the two modified processor files and the new test file. Do not commit.

---

### Task 2: Full analytics regression run and real-raster check

**Goal:** Confirm the new processors don't break the rest of the analytics suite (including lease tests that call `get_batch_func`), and that they give sensible values on a real raster.

**Files:**
- No source changes.

**Acceptance Criteria:**
- [ ] `manage.py test analytics` in the backend container ends with `OK`, or the only failures also fail on a clean `origin/main` checkout (record them)
- [ ] On the Hansen tree cover raster (values are percent tree cover, 0–100) with the first 10 Honduras ADM2 features, each feature's precise mean is within 1.0 of its default mean (measured max: 0.48, on a mostly coastal feature with mean ≈ 3.8), and precise count is at most default count, because the all_touched default count includes every touched edge pixel in full

**Verify:** `sudo docker compose exec -T backend uv run python manage.py test analytics` → `OK`

**Steps:**

- [ ] **Step 1: Bring the stack up** (it is usually down; Docker needs passwordless sudo)

Run: `cd /home/userx/git/geoquery && sudo docker compose up -d && sudo docker compose exec -T backend echo ok`
Expected: `ok`

- [ ] **Step 2: Run the analytics suite**

Run: `cd /home/userx/git/geoquery && sudo docker compose exec -T backend uv run python manage.py test analytics`
Expected: `OK`. If anything other than `test_precise_processors` fails, check whether it also fails without this change: run `git -C /home/userx/git/geoquery stash push -- backend/analytics/processors/zonal_stats_rasterstats.py backend/analytics/processors/__init__.py`, re-run only the failing test labels, then `git -C /home/userx/git/geoquery stash pop`, and report both results.

- [ ] **Step 3: Real-raster sanity check** (on the host; reads files outside the repo)

Run:

```bash
cd /home/userx/git/geoquery/backend && env DJANGO_SECRET_KEY=test-only-key DEBUG=True uv run python -c "
import json, shapely
from shapely.geometry import shape
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'geoquery.settings'); django.setup()
from analytics.processors import REGISTRY
r = '/home/userx/git/gates-eudr-honduras/data/Hansen_GFC-2024-v1.12_treecover2000_20N_090W.tif'
feats = [shape(f['geometry']) for f in json.load(open('/home/userx/git/gates-eudr-honduras/data/geoBoundaries-HND-ADM2.geojson'))['features'][:10]]
for g in feats:
    dm = REGISTRY['rasterstats_default_mean'](g, r, name='v')[0][1]; pm = REGISTRY['rasterstats_precise_mean'](g, r, name='v')[0][1]
    dc = REGISTRY['rasterstats_default_count'](g, r, name='v')[0][1]; pc = REGISTRY['rasterstats_precise_count'](g, r, name='v')[0][1]
    print(f'{dm:8.3f} {pm:8.3f} {abs(pm-dm):6.3f}   {dc:9d} {pc:12.1f}  {pc<=dc}')
"
```

Expected (takes ~20 s): 10 rows; the third column (absolute mean difference) under 1.0 on every row (prototype measured 0.025–0.48), the last column `True` on every row.

- [ ] **Step 4: Bring the stack down and report**

Run: `cd /home/userx/git/geoquery && sudo docker compose down`
Report the test summary and the sanity-check table. Do not commit.
