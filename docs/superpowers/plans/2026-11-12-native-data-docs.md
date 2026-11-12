# Native Data Docs Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate every data documentation page (one per dataset, plus grouped boundary pages that show coverage in both directions) natively in Django every night. The docs site downloads the result, so the pages stay current without anyone regenerating and committing them.

**Architecture:** A new `datasets.docs` package renders Markdown from the replica database. A nightly Celery beat task on the `background` queue writes `REQUESTS_DIR/docs/data-docs.tar.gz`, which the app already serves at `<app_url>/requests/docs/data-docs.tar.gz`. The docs workflow downloads that bundle, checks its manifest, unpacks the `datasets/` and `boundaries/` directories into `docs/data_documentation/`, and builds the site. The two old generators and their committed pages are removed.

**Tech Stack:** Django 5 / Celery / PostGIS (backend), Zensical (docs), GitHub Actions, Python stdlib (`tarfile`, `tomllib`, `urllib`) in the workflow script.

**User decisions (already made):**
- "generate all the dataset docs (existing and coverage) at the same time": one generator writes the dataset pages, the boundary pages and both indexes.
- "we can do this faster natively": no public API. The generator is Django code that reads the database.
- Option 1 ("lets reconsider your original option 1", then "yes"): the cluster writes a bundle into the requests share, the app serves it, and the docs workflow downloads it. No GitHub credential goes in the cluster, and nobody commits generated pages.
- "proceed like we can trust global flag": coverage comes from `is_global` plus `analytics.coverage.valid_coverage()`. The 9 regional datasets wrongly marked global are tracked in GEO-73 and are out of scope here.
- geoBoundaries: one page per country. "for gB let's strip the v6": the key `gb_v6_npl` becomes `gb_npl`, and the URL is `boundaries/gb-npl/`. Every release of a country shares that page, with versions listed under each ADM level.
- "for non gB lets use the group name": other sources get one page per `group_name`, at `boundaries/<slug of group_name>/`.
- "Two groups producing the same slug [should] just be on the same page", and "the source check is valid": keys that slugify the same share a page. The build fails only if a page would mix `source_name`s.
- Docs publish only from `main` (done in 3d369fff; the Pages environment allows `main` only).
- Commits, pushes, deploys and prod writes need the user's explicit go-ahead each time. Ask about a `[DEPLOY-X.Y.Z]` marker before committing backend work to `main`. No Claude attribution lines.
- Use `uv run manage.py`, not `python manage.py`. One-off prod commands run in `deploy/geoquery-import`.

---

## Facts the implementer needs

- **Tests run in Docker:** `sudo docker compose exec -T backend uv run manage.py test <labels>`. The stack is usually down; start it with `sudo docker compose up -d db backend` from the repo root.
- **Replica reads:** code reads through `.using("replica")`. Tests that touch that alias must mix in `geoquery.testing.ReplicaReadsTestMixin` ahead of `TestCase`.
- **Paths in prod:** `REQUESTS_DIR` is `/requests` there (the NFS share). Locally `./requests` is mounted at `/requests` in the backend container, and `/requests/` is git-ignored.
- **Routing:** the proxy sends `^/requests/[^/]+/.+` (two or more segments) to Django, which serves files from `REQUESTS_DIR`. So `/requests/docs/data-docs.tar.gz` is served, while `/requests/x` would go to the frontend.
- **Queue and pod:** tasks default to the `background` queue (`CELERY_TASK_DEFAULT_QUEUE`). The `background-worker` pod mounts `/requests` read-write, runs as uid 1000 / gid 9915, and the share is group-writable for gid 9915.
- **Cleanup won't touch the bundle:** the only job that cleans the share removes dot-prefixed `.<request_id>.building.*` / `.replaced.*` leftovers. A `docs/` directory is safe.
- **Coverage data:** global datasets have no coverage rows, because GeoQuery skips coverage for them. `valid_coverage(using)` returns status-1 rows, excluding datasets and collections that are being re-covered. In prod today all 63 public datasets are global and `coverage` is empty, so every boundary page lists all 63 (GEO-73).
- **Headings:** Zensical supports `{#id}` heading anchors (tested). A plain `.html` file under `docs/` is copied to the site unchanged (tested). `exclude_docs` is supported (tested).
- **Excluded from the old pages:** `FeatureCollection.is_user_upload` uploads. Keep excluding them.
- **Old geoBoundaries URLs:** the live `gb-57dcd43-npl-adm1`-style pages are `slug(collection.name)`. Each one becomes a redirect page to `../gb-npl/#gb-57dcd43-npl-adm1`.

## File structure

Create:
- `backend/datasets/docs/__init__.py`: package docstring only.
- `backend/datasets/docs/text.py`: slugs, Markdown cells, links, license text, date ranges, meta descriptions, front matter.
- `backend/datasets/docs/grouping.py`: the page rules (`page_key`, `Page`, `build_pages`, `GroupingError`).
- `backend/datasets/docs/coverage.py`: `page_coverage()`, mapping each page to the datasets covering it, from `is_global` and `valid_coverage()`.
- `backend/datasets/docs/render.py`: Markdown for dataset pages, boundary pages, both indexes and redirect stubs.
- `backend/datasets/docs/build.py`: loads from the replica, writes pages (`write_pages`, `build_data_docs`) and the atomic bundle (`build_bundle`).
- `backend/datasets/management/commands/build_data_docs.py`: the `--out DIR` (local preview) and `--bundle PATH` command.
- `backend/datasets/tests/test_docs_text.py`, `test_docs_grouping.py`, `test_docs_coverage.py`, `test_docs_render.py`, `test_docs_build.py`
- `.github/scripts/fetch_data_docs.py`: downloads, checks and unpacks the bundle in the docs workflow.
- `.github/scripts/test_fetch_data_docs.py`

Modify:
- `zensical.toml`: `exclude_docs` for `superpowers/`.
- `backend/datasets/tasks/__init__.py`: replace `build_dataset_docs_task` with `build_data_docs_task`.
- `backend/features/tasks/__init__.py`: remove `build_boundary_docs_task`.
- `backend/analytics/background_metrics.py`: add `"data_docs"` to `JOBS`.
- `backend/geoquery/settings.py`: add `DATA_DOCS_BUNDLE`, and replace the commented-out docs beat block (lines ~685–721) with a `build-data-docs` beat entry.
- `backend/analytics/tasks/documentation.py:7`: import `absolute_url` from `datasets.docs.text`.
- `.github/workflows/docs.yml`: schedule, manual dispatch, script tests, fetch step.
- `.gitignore`: ignore the generated directories.

Delete:
- `backend/datasets/tasks/create_docs.py`, `backend/features/tasks/create_docs.py`
- `backend/datasets/management/commands/build_dataset_docs.py`, `backend/features/management/commands/build_boundary_docs.py`
- `backend/datasets/tests/test_create_docs.py`, and the `BoundaryDocsPageTests` class at the end of `backend/features/tests.py`
- the committed `docs/data_documentation/datasets/` and `docs/data_documentation/boundaries/` (`git rm -r`)

---

### Task 1: Keep internal plans and specs off the docs site

**Goal:** `docs/superpowers/` (plans and specs) stops being published on docs.geoquery.org and listed in its sitemap.

**Files:**
- Modify: `zensical.toml` (the `[project]` table, after `site_url`)

**Acceptance Criteria:**
- [ ] `uv run --only-group docs zensical build --clean --strict` reports "No issues found".
- [ ] `site/superpowers/` does not exist after the build.
- [ ] `grep -c superpowers site/sitemap.xml` prints `0`.

**Verify:** `uv run --only-group docs zensical build --clean --strict && test ! -e site/superpowers && grep -c superpowers site/sitemap.xml` → build OK, then `0`.

**Steps:**

- [ ] **Step 1: Add `exclude_docs`** directly below the `site_url = "https://docs.geoquery.org/"` line in `zensical.toml`:

```toml
# Implementation plans and design specs live beside the docs for convenience,
# but are internal: keep them out of the published site and its sitemap.
exclude_docs = """
superpowers/
"""
```

- [ ] **Step 2: Build and check**

Run: `uv run --only-group docs zensical build --clean --strict && test ! -e site/superpowers && grep -c superpowers site/sitemap.xml`
Expected: "No issues found", then `0`.

- [ ] **Step 3: Commit** (only with the user's go-ahead; no deploy marker, since this is docs only)

```bash
git add zensical.toml
git commit -m "Keep internal plans and specs off the docs site"
```

---

### Task 2: Text helpers and page grouping rules

**Goal:** `datasets.docs.text` and `datasets.docs.grouping` implement the slug, description and grouping rules, with unit tests.

**Files:**
- Create: `backend/datasets/docs/__init__.py`, `backend/datasets/docs/text.py`, `backend/datasets/docs/grouping.py`
- Test: `backend/datasets/tests/test_docs_text.py`, `backend/datasets/tests/test_docs_grouping.py`

**Acceptance Criteria:**
- [ ] `page_key` maps `gb_v6_npl` and `gb_v7_npl` to `gb_npl`, a non-geoBoundaries group to its `group_name`, and a collection without a group to its own name. `gb_custom` is not treated as geoBoundaries.
- [ ] `build_pages` puts collections whose keys share a slug on one page, and raises `GroupingError` if that page mixes `source_name`s or its slug is empty.
- [ ] Collections on a page are ordered by level (missing levels last), then newest `date_added`, then time period, then title.
- [ ] `meta_description` never exceeds 160 characters and never cuts `detail` mid-sentence.
- [ ] All tests in both new files pass.

**Verify:** `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_text datasets.tests.test_docs_grouping` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests**

`backend/datasets/tests/test_docs_text.py`:

```python
from datetime import datetime, timezone

from django.test import SimpleTestCase

from datasets.docs.text import (
    DESCRIPTION_LIMIT,
    absolute_url,
    cell,
    date_range,
    front_matter,
    join_words,
    meta_description,
    slug,
    year_range,
)


def dt(year, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


class SlugTests(SimpleTestCase):
    def test_lowercases_and_hyphenates(self):
        self.assertEqual(slug("gB_57dcd43_NPL_ADM1"), "gb-57dcd43-npl-adm1")
        self.assertEqual(slug("TIGER"), "tiger")

    def test_empty(self):
        self.assertEqual(slug("__"), "")
        self.assertEqual(slug(None), "")


class CellTests(SimpleTestCase):
    def test_one_line_with_pipes_escaped(self):
        self.assertEqual(cell("a |\n b"), "a \\| b")

    def test_dash_when_empty(self):
        self.assertEqual(cell(None), "—")


class UrlTests(SimpleTestCase):
    def test_scheme_is_added_when_missing(self):
        self.assertEqual(absolute_url("www.geoboundaries.org"), "https://www.geoboundaries.org")
        self.assertEqual(absolute_url("http://x.org"), "http://x.org")
        self.assertEqual(absolute_url(None), "")


class RangeTests(SimpleTestCase):
    def test_year_range(self):
        self.assertEqual(year_range(dt(2000), dt(2020)), "2000–2020")
        self.assertEqual(year_range(dt(2015), dt(2015, 12)), "2015")
        self.assertEqual(year_range(None, None), "—")

    def test_date_range(self):
        self.assertEqual(date_range(dt(2000), None), "2000-01-01 – —")


class JoinWordsTests(SimpleTestCase):
    def test_joins_with_and(self):
        self.assertEqual(join_words(["a"]), "a")
        self.assertEqual(join_words(["a", "b", "c"]), "a, b and c")


class MetaDescriptionTests(SimpleTestCase):
    def test_lead_detail_and_suffix_are_joined(self):
        self.assertEqual(meta_description("Malaria.", "Cases.", " More."), "Malaria. Cases. More.")

    def test_detail_that_does_not_fit_falls_back_to_its_first_sentence(self):
        detail = "Short first sentence. " + "word " * 40
        self.assertEqual(meta_description("Lead.", detail), "Lead. Short first sentence.")

    def test_detail_is_dropped_rather_than_cut(self):
        self.assertEqual(meta_description("Lead.", "word " * 40 + ".", " Suffix."), "Lead. Suffix.")

    def test_overlong_lead_is_cut_at_a_word(self):
        result = meta_description("word " * 100, "Detail.", " Suffix.")
        self.assertLessEqual(len(result), DESCRIPTION_LIMIT)
        self.assertTrue(result.endswith("word… Suffix."))


class FrontMatterTests(SimpleTestCase):
    def test_description_is_quoted(self):
        self.assertEqual(
            front_matter('Rain: "monthly" #1'),
            '---\ndescription: "Rain: \\"monthly\\" #1"\n---\n\n',
        )
```

`backend/datasets/tests/test_docs_grouping.py`:

```python
from datetime import datetime, timezone

from django.test import SimpleTestCase

from datasets.docs.grouping import (
    GroupingError,
    build_pages,
    gb_version,
    level_label,
    page_key,
)
from features.models import FeatureCollection


def fc(name, group_name=None, level=None, added=2026, title=None, source="geoBoundaries",
       group_title=None):
    return FeatureCollection(
        name=name, group_name=group_name, group_level=level, title=title or name,
        source_name=source, group_title=group_title,
        date_added=datetime(added, 1, 1, tzinfo=timezone.utc),
    )


class PageKeyTests(SimpleTestCase):
    def test_geoboundaries_drops_the_release(self):
        self.assertEqual(page_key(fc("gB_57dcd43_NPL_ADM1", "gb_v6_npl")), "gb_npl")
        self.assertEqual(page_key(fc("gB_x_NPL_ADM1", "GB_V7_NPL")), "gb_npl")

    def test_other_groups_keep_their_name(self):
        self.assertEqual(page_key(fc("TIGER_2025_COUNTY", "TIGER")), "TIGER")
        self.assertEqual(page_key(fc("gb_custom_thing", "gb_custom")), "gb_custom")

    def test_ungrouped_collection_uses_its_own_name(self):
        self.assertEqual(page_key(fc("lonely")), "lonely")


class BuildPagesTests(SimpleTestCase):
    def test_every_release_of_a_country_shares_one_page(self):
        pages = build_pages([
            fc("gB_57dcd43_NPL_ADM1", "gb_v6_npl", 1, added=2026),
            fc("gB_old_NPL_ADM1", "gb_v5_npl", 1, added=2024),
            fc("gB_57dcd43_NPL_ADM0", "gb_v6_npl", 0, added=2026),
        ])
        self.assertEqual([p.slug for p in pages], ["gb-npl"])
        self.assertEqual(
            [c.name for c in pages[0].collections],
            ["gB_57dcd43_NPL_ADM0", "gB_57dcd43_NPL_ADM1", "gB_old_NPL_ADM1"],
        )

    def test_keys_that_slugify_the_same_share_a_page(self):
        pages = build_pages([
            fc("a", "TIGER", source="US Census"),
            fc("b", "tiger", source="US Census"),
        ])
        self.assertEqual([p.slug for p in pages], ["tiger"])

    def test_a_page_mixing_sources_is_an_error(self):
        with self.assertRaisesRegex(GroupingError, "boundaries/tiger/"):
            build_pages([fc("a", "TIGER", source="US Census"), fc("b", "tiger", source="Other")])

    def test_an_empty_slug_is_an_error(self):
        with self.assertRaises(GroupingError):
            build_pages([fc("x", "__")])

    def test_collections_without_a_level_come_last(self):
        page = build_pages([fc("b", "g", None, source="s"), fc("a", "g", 2, source="s")])[0]
        self.assertEqual([c.name for c in page.collections], ["a", "b"])


class PageTitleTests(SimpleTestCase):
    def test_geoboundaries_page_is_named_after_the_country(self):
        page = build_pages([fc("gB_x_NPL_ADM0", "gb_v6_npl", 0, group_title="Nepal - GeoBoundaries v6")])[0]
        self.assertTrue(page.geoboundaries)
        self.assertEqual(page.place, "Nepal")
        self.assertEqual(page.title, "Nepal boundaries")

    def test_other_pages_use_the_group_title(self):
        page = build_pages([fc("a", "atlas", source="s", group_title="Atlas of Urban Expansion")])[0]
        self.assertFalse(page.geoboundaries)
        self.assertEqual(page.title, "Atlas of Urban Expansion")


class LevelLabelTests(SimpleTestCase):
    def test_geoboundaries_label_uses_the_canonical_name(self):
        c = fc("gB_x_NPL_ADM1", "gb_v6_npl", 1, title="geoBoundaries v6 - Nepal ADM1 (Provinces)")
        self.assertEqual(level_label(c), "ADM1 (Provinces)")

    def test_other_levels_and_missing_levels(self):
        self.assertEqual(level_label(fc("a", "TIGER", 2)), "Level 2")
        self.assertEqual(level_label(fc("a", "atlas")), "")

    def test_sections_group_consecutive_levels(self):
        page = build_pages([
            fc("gB_a_NPL_ADM1", "gb_v6_npl", 1, title="X ADM1 (Provinces)", added=2026),
            fc("gB_b_NPL_ADM1", "gb_v5_npl", 1, title="X ADM1 (Provinces)", added=2024),
        ])[0]
        self.assertEqual([(h, len(m)) for h, m in page.sections()], [("ADM1 (Provinces)", 2)])


class VersionTests(SimpleTestCase):
    def test_version_comes_from_the_collection_name(self):
        self.assertEqual(gb_version(fc("gB_57dcd43_NPL_ADM1")), "57dcd43")
        self.assertIsNone(gb_version(fc("TIGER_2025_COUNTY")))
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_text datasets.tests.test_docs_grouping`
Expected: `ModuleNotFoundError: No module named 'datasets.docs'`.

- [ ] **Step 3: Write the modules**

`backend/datasets/docs/__init__.py`:

```python
"""Generate the data documentation pages (datasets and boundaries) for the docs site.

build.build_bundle runs nightly in the cluster (datasets.tasks.build_data_docs_task)
and writes a tarball into the requests share. The docs workflow downloads it from
<app_url>/requests/docs/data-docs.tar.gz (.github/scripts/fetch_data_docs.py).
"""
```

`backend/datasets/docs/text.py`:

```python
"""Text helpers shared by the data documentation pages."""

import json
import re

# Search engines show roughly this many characters of a meta description.
DESCRIPTION_LIMIT = 160


def slug(value) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def one_line(text) -> str:
    return " ".join(str(text or "").split())


def cell(text) -> str:
    """A Markdown table cell: one line, pipes escaped, a dash when empty."""
    return one_line(text).replace("|", "\\|") or "—"


def absolute_url(url) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def link(label, url) -> str:
    url = absolute_url(url)
    return f"[{label}]({url})" if url else label


def license_text(obj) -> str:
    """Always says something. GeoQuery redistributes other people's data under
    their terms, so "not recorded, check the source" is information the reader
    needs, not a row to drop."""
    if not obj.license:
        return "Not recorded — see the source link"
    return link(cell(obj.license), obj.license_url)


def year_range(start, end) -> str:
    """'2000–2020', '2015' when both fall in one year, or '—' with neither."""
    first, last = (f"{d:%Y}" if d else "" for d in (start, end))
    if first and last and first != last:
        return f"{first}–{last}"
    return first or last or "—"


def date_range(start, end) -> str:
    first, last = (f"{d:%Y-%m-%d}" if d else "—" for d in (start, end))
    return f"{first} – {last}"


def join_words(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def meta_description(lead, detail=None, suffix: str = "") -> str:
    """A page's meta description, at most DESCRIPTION_LIMIT characters: ``lead``
    then ``suffix``, with as much of ``detail`` between them as fits whole --
    all of it, else its first sentence, else none. Only an overlong ``lead`` is
    ever cut mid-text, at a word."""
    lead, detail = one_line(lead), one_line(detail)
    room = DESCRIPTION_LIMIT - len(suffix)
    if len(lead) > room:
        lead = lead[: room - 1].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    first_sentence = re.split(r"(?<=[.!?])\s", detail, maxsplit=1)[0]
    for candidate in (detail, first_sentence):
        if candidate and len(lead) + 1 + len(candidate) <= room:
            lead = f"{lead} {candidate}"
            break
    return (lead + suffix).strip()


def front_matter(description: str) -> str:
    """YAML front matter setting the page's meta description. JSON string
    syntax is valid YAML, and quoting keeps colons and hashes literal."""
    return f"---\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n"
```

`backend/datasets/docs/grouping.py`:

```python
"""Which docs page each boundary collection goes on.

Rules, decided 2026-11-12:

- A collection's page key is its group_name, or its own name when it has none.
- geoBoundaries group names (gb_v<N>_<iso3>) drop the release, so gb_v6_npl
  becomes gb_npl and every release of a country shares one page.
- The page's URL slug is slug(key): gb-npl, tiger, atlasofurbanexpansion2016.
- Collections whose keys give the same slug share a page.
- A page that would mix collections from different sources is an error, so
  two unrelated ingests that happen to collide can't merge silently.
"""

import re
from dataclasses import dataclass

from .text import slug

GB_GROUP = re.compile(r"^gb_v\d+_([a-z]{3})$", re.IGNORECASE)
GB_NAME = re.compile(r"^gB_([^_]+)_[A-Za-z]{3}_ADM\d+$")
CANONICAL = re.compile(r"\(([^()]+)\)\s*$")


class GroupingError(ValueError):
    pass


def page_key(fc) -> str:
    key = fc.group_name or fc.name
    match = GB_GROUP.match(key)
    return f"gb_{match.group(1).lower()}" if match else key


def is_geoboundaries(fc) -> bool:
    return bool(GB_GROUP.match(fc.group_name or ""))


def gb_version(fc):
    """The geoBoundaries build a collection came from: gB_57dcd43_NPL_ADM1 -> 57dcd43."""
    match = GB_NAME.match(fc.name)
    return match.group(1) if match else None


def level_label(fc) -> str:
    """'ADM1 (Provinces)' for geoBoundaries, 'Level 2' otherwise, '' with no level."""
    if fc.group_level is None:
        return ""
    if is_geoboundaries(fc):
        base = f"ADM{fc.group_level}"
        match = CANONICAL.search(fc.title or "")
        return f"{base} ({match.group(1)})" if match else base
    return f"Level {fc.group_level}"


def _ordered(collections):
    # Stable sorts, least significant key first: title, time period, newest
    # added, then level (missing levels last).
    out = sorted(collections, key=lambda fc: (
        fc.temporal_start.isoformat() if fc.temporal_start else "", fc.title or fc.name,
    ))
    out = sorted(out, key=lambda fc: fc.date_added, reverse=True)
    return sorted(out, key=lambda fc: (fc.group_level is None, fc.group_level or 0))


@dataclass
class Page:
    slug: str
    collections: list

    @property
    def geoboundaries(self) -> bool:
        return all(is_geoboundaries(fc) for fc in self.collections)

    @property
    def _newest(self):
        return max(self.collections, key=lambda fc: fc.date_added)

    @property
    def place(self) -> str:
        """The country for a geoBoundaries page ("Nepal"), else the group's title."""
        newest = self._newest
        if self.geoboundaries:
            return (newest.group_title or "").split(" - ")[0].strip() or newest.name
        return newest.group_title or newest.group_name or newest.title or newest.name

    @property
    def title(self) -> str:
        return f"{self.place} boundaries" if self.geoboundaries else self.place

    def sections(self):
        """[(heading, [collections])], in page order. A '' heading means the
        collections have no level, and each gets a section of its own."""
        out = []
        for fc in self.collections:
            label = level_label(fc)
            if out and out[-1][0] == label:
                out[-1][1].append(fc)
            else:
                out.append((label, [fc]))
        return out


def build_pages(collections) -> list:
    by_slug = {}
    for fc in collections:
        by_slug.setdefault(slug(page_key(fc)), []).append(fc)
    pages = []
    for page_slug, members in by_slug.items():
        names = sorted(fc.name for fc in members)
        if not page_slug:
            raise GroupingError(f"collections {names} have a group name with no usable characters")
        sources = sorted({fc.source_name or "" for fc in members})
        if len(sources) > 1:
            raise GroupingError(
                f"boundaries/{page_slug}/ would mix sources {sources}: {names}. "
                "Give one of these ingests a different group_name."
            )
        pages.append(Page(page_slug, _ordered(members)))
    return sorted(pages, key=lambda page: page.title.lower())
```

- [ ] **Step 4: Run the tests**

Run: `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_text datasets.tests.test_docs_grouping`
Expected: `OK`.

- [ ] **Step 5: Commit** (only with the user's go-ahead)

```bash
git add backend/datasets/docs backend/datasets/tests/test_docs_text.py backend/datasets/tests/test_docs_grouping.py
git commit -m "Add data docs text helpers and boundary page grouping rules"
```

---

### Task 3: Page coverage

**Goal:** `datasets.docs.coverage.page_coverage()` returns, for each boundary page, the datasets that cover it, each marked full or partial. Global datasets cover every page in full; other datasets cover a page through `valid_coverage()` rows.

**Files:**
- Create: `backend/datasets/docs/coverage.py`
- Test: `backend/datasets/tests/test_docs_coverage.py`

**Acceptance Criteria:**
- [ ] A global dataset is `FULL` on every page.
- [ ] A regional dataset with status-1 rows for every feature on a page is `FULL`, with rows for some features is `PARTIAL`, and with none is absent.
- [ ] Rows with status other than 1 don't count.
- [ ] Tests pass.

**Verify:** `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_coverage` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests**

`backend/datasets/tests/test_docs_coverage.py`:

```python
from django.test import TestCase

from analytics.models import Coverage
from datasets.docs.coverage import FULL, PARTIAL, page_coverage
from datasets.docs.grouping import build_pages
from datasets.models import Dataset
from features.models import Feature, FeatMap, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin


def dataset(name, is_global):
    return Dataset.objects.create(name=name, path=f"/{name}", type="raster", title=name,
                                  is_global=is_global, active=True, public=True)


class PageCoverageTests(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        self.fc = FeatureCollection.objects.create(
            name="gB_x_NPL_ADM1", path="/npl1", group_name="gb_v6_npl", group_level=1,
            source_name="geoBoundaries", active=True, public=True,
        )
        self.features = []
        for _ in range(2):
            feature = Feature.objects.create(shape="POINT(0 0)")
            FeatMap.objects.create(fc=self.fc, geom=feature)
            self.features.append(feature)
        self.pages = build_pages([self.fc])

    def test_global_dataset_covers_every_page_in_full(self):
        world = dataset("world", True)
        self.assertEqual(page_coverage(self.pages, [world]), {"gb-npl": {world.id: FULL}})

    def test_regional_dataset_full_partial_and_absent(self):
        full, partial, absent = dataset("full", False), dataset("partial", False), dataset("absent", False)
        for feature in self.features:
            Coverage.objects.create(dataset=full, geom=feature, status=1)
        Coverage.objects.create(dataset=partial, geom=self.features[0], status=1)
        Coverage.objects.create(dataset=absent, geom=self.features[0], status=0)

        result = page_coverage(self.pages, [full, partial, absent])

        self.assertEqual(result["gb-npl"], {full.id: FULL, partial.id: PARTIAL})
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_coverage`
Expected: `ModuleNotFoundError: No module named 'datasets.docs.coverage'`.

- [ ] **Step 3: Write the module**

`backend/datasets/docs/coverage.py`:

```python
"""Which datasets cover which boundary pages, from GeoQuery's own coverage data.

A global dataset covers every page in full: GeoQuery skips coverage for global
datasets, so they have no rows. Any other dataset covers a page where valid
coverage rows (analytics.coverage.valid_coverage) exist for the page's
features -- in full when every feature is covered, partially otherwise.

This trusts is_global. Datasets wrongly marked global will show as covering
everything until their flag is fixed (GEO-73).
"""

from collections import defaultdict

from django.db.models import Count

FULL = "full"
PARTIAL = "partial"


def page_coverage(pages, datasets, using="replica") -> dict:
    """{page.slug: {dataset.id: FULL | PARTIAL}} for every page."""
    from analytics.coverage import valid_coverage
    from features.models import FeatMap

    fc_page = {fc.id: page.slug for page in pages for fc in page.collections}
    totals = defaultdict(int)
    counts = (
        FeatMap.objects.using(using).filter(fc_id__in=list(fc_page))
        .values("fc_id").annotate(n=Count("id")).values_list("fc_id", "n")
    )
    for fc_id, n in counts:
        totals[fc_page[fc_id]] += n

    result = {page.slug: {ds.id: FULL for ds in datasets if ds.is_global} for page in pages}
    regional = [ds.id for ds in datasets if not ds.is_global]
    if not regional:
        return result

    covered = defaultdict(int)
    rows = (
        valid_coverage(using)
        .filter(dataset_id__in=regional, geom__featmap__fc_id__in=list(fc_page))
        .values("dataset_id", "geom__featmap__fc_id")
        .annotate(n=Count("geom_id", distinct=True))
    )
    for row in rows:
        covered[(fc_page[row["geom__featmap__fc_id"]], row["dataset_id"])] += row["n"]
    for (page_slug, dataset_id), n in covered.items():
        result[page_slug][dataset_id] = FULL if n >= totals[page_slug] else PARTIAL
    return result
```

- [ ] **Step 4: Run the tests**

Run: `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_coverage`
Expected: `OK`.

- [ ] **Step 5: Commit** (only with the user's go-ahead)

```bash
git add backend/datasets/docs/coverage.py backend/datasets/tests/test_docs_coverage.py
git commit -m "Add page coverage for the data docs from is_global and valid coverage"
```

---

### Task 4: Page rendering

**Goal:** `datasets.docs.render` produces the Markdown for dataset pages, boundary pages, both indexes and the redirect stubs.

**Files:**
- Create: `backend/datasets/docs/render.py`
- Test: `backend/datasets/tests/test_docs_render.py`

**Acceptance Criteria:**
- [ ] A dataset page starts with front matter, has Details, "Available for" (the text "Every boundary in GeoQuery." for global datasets, otherwise a table linking `../boundaries/<slug>.md` with Full/Partial), Resources, Value Mappings and Citation.
- [ ] A geoBoundaries page is titled "<Country> boundaries", has `## ADM1 (Provinces) {#adm1}` sections, `### <title> {#<slug of collection name>}` per collection with its feature count and version, a "Datasets for <Country>" table linking `../datasets/<slug>.md`, and one Citation section when the collections share a citation.
- [ ] The boundary page description names up to four topics from the covering datasets' tags, in `TOPICS` order.
- [ ] `redirect_html` contains a `noindex` meta tag, a meta refresh to the target, and a canonical link.
- [ ] Tests pass.

**Verify:** `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_render` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests**

`backend/datasets/tests/test_docs_render.py`:

```python
from datetime import datetime, timezone

from django.test import TestCase

from datasets.docs.coverage import FULL, PARTIAL
from datasets.docs.grouping import build_pages
from datasets.docs.render import (
    boundaries_index,
    boundary_page,
    dataset_page,
    datasets_index,
    redirect_html,
    topics,
)
from datasets.models import Dataset, DatasetResource, Mapping
from features.models import FeatureCollection

ADDED = datetime(2026, 8, 18, tzinfo=timezone.utc)


def make_dataset(name="malaria", **kw):
    kw.setdefault("title", "Malaria Incidence")
    kw.setdefault("description", "Plasmodium falciparum incidence rate.")
    return Dataset.objects.create(name=name, path=f"/{name}", type="raster", active=True, public=True, **kw)


def make_fc(name, level, **kw):
    fc = FeatureCollection.objects.create(
        name=name, path=f"/{name}", group_name="gb_v6_npl", group_level=level,
        group_title="Nepal - GeoBoundaries v6", source_name="geoBoundaries",
        source_url="https://www.geoboundaries.org", active=True, public=True,
        citation="Runfola, D. et al. (2020) geoBoundaries.", **kw,
    )
    FeatureCollection.objects.filter(id=fc.id).update(date_added=ADDED)
    fc.date_added = ADDED
    return fc


class DatasetPageTests(TestCase):
    def test_global_dataset(self):
        ds = make_dataset(is_global=True, citation="MAP (2026).", tags=["malaria", "health"])
        DatasetResource.objects.create(dataset=ds, name="malaria_2020", path="/x", label="2020",
                                       temporal=datetime(2020, 1, 1, tzinfo=timezone.utc))
        Mapping.objects.create(dataset=ds, map_val=1, map_name="Low")

        page = dataset_page(ds, [])

        self.assertTrue(page.startswith('---\ndescription: "Malaria Incidence. Plasmodium'))
        self.assertIn("# Malaria Incidence\n", page)
        self.assertIn("| License | Not recorded — see the source link |", page)
        self.assertIn("## Available for\n\nEvery boundary in GeoQuery.", page)
        self.assertIn("| malaria_2020 | 2020 | 2020-01-01 |", page)
        self.assertIn("| 1 | Low |", page)
        self.assertIn("## Citation\n\nMAP (2026).", page)

    def test_regional_dataset_lists_its_pages(self):
        ds = make_dataset(is_global=False)
        nepal = build_pages([make_fc("gB_57dcd43_NPL_ADM0", 0)])[0]
        page = dataset_page(ds, [(nepal, PARTIAL)])
        self.assertIn("| [Nepal boundaries](../boundaries/gb-npl.md) | Partial |", page)


class BoundaryPageTests(TestCase):
    def setUp(self):
        self.adm0 = make_fc("gB_57dcd43_NPL_ADM0", 0, title="geoBoundaries v6 - Nepal ADM0 (Country)")
        self.adm1 = make_fc("gB_57dcd43_NPL_ADM1", 1, title="geoBoundaries v6 - Nepal ADM1 (Provinces)")
        self.page = build_pages([self.adm0, self.adm1])[0]
        self.malaria = make_dataset(tags=["malaria"], is_global=True)
        self.pop = make_dataset("pop", title="Population", description="", tags=["population"])

    def render(self):
        covering = [(self.malaria, FULL), (self.pop, FULL)]
        return boundary_page(self.page, covering, {self.adm0.id: 1, self.adm1.id: 7}, "https://app.example")

    def test_structure(self):
        page = self.render()
        self.assertIn("# Nepal boundaries\n", page)
        self.assertIn("## ADM1 (Provinces) {#adm1}", page)
        self.assertIn("### geoBoundaries v6 - Nepal ADM1 (Provinces) {#gb-57dcd43-npl-adm1}", page)
        self.assertIn("| Features | 7 |", page)
        self.assertIn("| geoBoundaries version | 57dcd43 |", page)
        self.assertIn("[GeoQuery](https://app.example)", page)
        self.assertIn("## Datasets for Nepal {#datasets}", page)
        self.assertIn("| [Malaria Incidence](../datasets/malaria.md) | — | Full |", page)
        self.assertEqual(page.count("## Citation"), 1)

    def test_description_names_topics(self):
        description = self.render().split("\n")[1]
        self.assertIn("Nepal administrative boundaries from geoBoundaries, ADM0 to ADM1.", description)
        self.assertIn("including population and malaria", description)


class TopicsTests(TestCase):
    def test_order_and_limit(self):
        datasets = [Dataset(tags=["malaria", "conflict"]), Dataset(tags=["population", "landcover"]),
                    Dataset(tags=["nighttimelights"])]
        self.assertEqual(topics(datasets), ["population", "nighttime lights", "malaria", "conflict"])


class IndexTests(TestCase):
    def test_datasets_index_links_every_dataset(self):
        index = datasets_index([make_dataset()])
        self.assertIn("| [Malaria Incidence](malaria.md) | raster |", index)

    def test_boundaries_index_lists_countries(self):
        pages = build_pages([make_fc("gB_57dcd43_NPL_ADM0", 0), make_fc("gB_57dcd43_NPL_ADM2", 2)])
        self.assertIn("| [Nepal](gb-npl.md) | ADM0–ADM2 |", boundaries_index(pages))


class RedirectTests(TestCase):
    def test_redirect_stub(self):
        stub = redirect_html("../gb-npl/#gb-57dcd43-npl-adm1")
        self.assertIn('<meta name="robots" content="noindex">', stub)
        self.assertIn('content="0; url=../gb-npl/#gb-57dcd43-npl-adm1"', stub)
        self.assertIn('<link rel="canonical" href="../gb-npl/#gb-57dcd43-npl-adm1">', stub)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_render`
Expected: `ModuleNotFoundError: No module named 'datasets.docs.render'`.

- [ ] **Step 3: Write the module**

`backend/datasets/docs/render.py`:

```python
"""Markdown for the data documentation pages. Pure functions of model objects."""

import html

from .coverage import FULL
from .grouping import gb_version
from .text import (
    cell,
    date_range,
    front_matter,
    join_words,
    license_text,
    link,
    meta_description,
    one_line,
    slug,
    year_range,
)

DATASET_SUFFIX = " Free to extract with AidData GeoQuery."
BOUNDARY_SUFFIX = " Free with AidData GeoQuery."
GEOBOUNDARIES_URL = "https://www.geoboundaries.org"

# Tag -> phrase, in the order a boundary page's description names them.
TOPICS = (
    ("population", "population"),
    ("nighttimelights", "nighttime lights"),
    ("malaria", "malaria"),
    ("conflict", "conflict"),
    ("precipitation", "rainfall"),
    ("temperature", "temperature"),
    ("air quality", "air quality"),
    ("land cover", "land cover"),
    ("landcover", "land cover"),
)


def topics(datasets, limit: int = 4) -> list:
    tags = {tag for ds in datasets for tag in (ds.tags or [])}
    found = []
    for tag, phrase in TOPICS:
        if tag in tags and phrase not in found:
            found.append(phrase)
    return found[:limit]


def _table(rows) -> str:
    rows = [(label, value) for label, value in rows if value]
    if not rows:
        return ""
    return "| | |\n|---|---|\n" + "".join(f"| {label} | {value} |\n" for label, value in rows) + "\n"


def _coverage_label(status) -> str:
    return "Full" if status == FULL else "Partial"


def _title(obj) -> str:
    return obj.title or obj.name


def dataset_page(ds, available) -> str:
    """``available``: [(Page, status)] in display order; unused for global datasets."""
    title = _title(ds)
    out = [front_matter(meta_description(f"{title}.", ds.description, DATASET_SUFFIX)), f"# {title}\n\n"]
    if ds.description:
        out.append(f"{one_line(ds.description)}\n\n")
    if ds.details:
        out.append(f"{ds.details.strip()}\n\n")

    variable = cell(ds.variable_description) if ds.variable_description else ""
    if variable and ds.variable_factor not in (None, 1.0):
        variable += f" (factor: {ds.variable_factor})"
    has_period = ds.temporal_start or ds.temporal_end
    out.append("## Details\n\n")
    out.append(_table([
        ("Type", cell(ds.type)),
        (cell(ds.temporal_name or "Time period"), date_range(ds.temporal_start, ds.temporal_end) if has_period else ""),
        ("Temporal type", cell(ds.temporal_type) if ds.temporal_type else ""),
        ("Tags", cell(", ".join(ds.tags)) if ds.tags else ""),
        ("Variable", variable),
        ("Source", link(cell(ds.source_name), ds.source_url) if ds.source_name else ""),
        ("License", license_text(ds)),
    ]))

    out.append("## Available for\n\n")
    if ds.is_global:
        out.append("Every boundary in GeoQuery.\n\n")
    elif available:
        out.append("| Boundaries | Coverage |\n|---|---|\n")
        out.extend(
            f"| [{cell(page.title)}](../boundaries/{page.slug}.md) | {_coverage_label(status)} |\n"
            for page, status in available
        )
        out.append("\n")
    else:
        out.append("No boundaries in GeoQuery are within this dataset's coverage yet.\n\n")

    resources = list(ds.resources.all())
    if resources:
        out.append("## Resources\n\n| Name | Label | Date |\n|---|---|---|\n")
        out.extend(
            f"| {cell(r.name)} | {cell(r.label)} | {f'{r.temporal:%Y-%m-%d}' if r.temporal else '—'} |\n"
            for r in resources
        )
        out.append("\n")
    mappings = list(ds.mappings.all())
    if mappings:
        out.append("## Value Mappings\n\n| Value | Label |\n|---|---|\n")
        out.extend(f"| {m.map_val} | {cell(m.map_name)} |\n" for m in mappings)
        out.append("\n")
    if ds.citation:
        out.append(f"## Citation\n\n{one_line(ds.citation)}\n")
    return "".join(out)


def _collection_block(fc, depth: int, feature_count: int, geoboundaries: bool) -> str:
    out = [f"{'#' * depth} {_title(fc)} {{#{slug(fc.name)}}}\n\n"]
    if fc.description and not geoboundaries:
        out.append(f"{one_line(fc.description)}\n\n")
    if fc.details:
        out.append(f"{one_line(fc.details)}\n\n")
    version = gb_version(fc) if geoboundaries else None
    has_period = fc.temporal_start or fc.temporal_end
    out.append(_table([
        ("Features", f"{feature_count:,}"),
        ("geoBoundaries version", cell(version) if version else ""),
        ("Added to GeoQuery", f"{fc.date_added:%Y-%m-%d}" if fc.date_added else ""),
        (cell(fc.temporal_name or "Time period"), year_range(fc.temporal_start, fc.temporal_end) if has_period else ""),
        ("Source", link(cell(fc.source_name), fc.source_url) if fc.source_name else ""),
        ("License", license_text(fc)),
    ]))
    return "".join(out)


def boundary_page(page, covering, feature_counts, app_url) -> str:
    """``covering``: [(Dataset, status)] in display order."""
    datasets = [ds for ds, _ in covering]
    if page.geoboundaries:
        top = max(fc.group_level or 0 for fc in page.collections)
        lead = f"{page.place} administrative boundaries from geoBoundaries, ADM0 to ADM{top}."
        intro = (
            f"Administrative boundaries for {page.place} from [geoBoundaries]({GEOBOUNDARIES_URL}), "
            f"ready to use in [GeoQuery]({app_url}) to extract data for each area.\n\n"
        )
    else:
        n = len(page.collections)
        lead = f"{page.title}: {n} boundary set{'' if n == 1 else 's'}."
        newest = max(page.collections, key=lambda fc: fc.date_added)
        intro = f"{one_line(newest.description)}\n\n" if newest.description else ""
    detail = None
    if datasets:
        found = topics(datasets)
        detail = f"Extract {len(datasets)} datasets for them"
        detail += f", including {join_words(found)}." if found else "."

    out = [front_matter(meta_description(lead, detail, BOUNDARY_SUFFIX)), f"# {page.title}\n\n", intro]
    for heading, members in page.sections():
        depth = 2
        if heading:
            out.append(f"## {heading} {{#{slug(heading.split(' (')[0])}}}\n\n")
            depth = 3
        for fc in members:
            out.append(_collection_block(fc, depth, feature_counts.get(fc.id, 0), page.geoboundaries))

    out.append(f"## Datasets for {page.place} {{#datasets}}\n\n")
    if covering:
        out.append("| Dataset | Time period | Coverage |\n|---|---|---|\n")
        out.extend(
            f"| [{cell(_title(ds))}](../datasets/{slug(ds.name)}.md) | "
            f"{year_range(ds.temporal_start, ds.temporal_end)} | {_coverage_label(status)} |\n"
            for ds, status in covering
        )
        out.append("\n")
    else:
        out.append("No datasets in GeoQuery cover these boundaries yet.\n\n")

    citations = list(dict.fromkeys(one_line(fc.citation) for fc in page.collections if fc.citation))
    if citations:
        out.append("## Citation\n\n" + "\n\n".join(citations) + "\n")
    return "".join(out)


def datasets_index(datasets) -> str:
    out = [
        front_matter(
            f"All {len(datasets)} datasets in AidData GeoQuery: population, nighttime lights, "
            "climate, land cover, conflict, health and more, free to extract for any boundary."
        ),
        "# Datasets\n\n",
        "Every dataset available in GeoQuery. Select one for its details, coverage and citation.\n\n",
        "| Dataset | Type | Time period | License | Description |\n|---|---|---|---|---|\n",
    ]
    for ds in sorted(datasets, key=lambda d: _title(d).lower()):
        description = one_line(ds.description)
        if len(description) > 120:
            description = description[:119].rsplit(" ", 1)[0] + "…"
        out.append(
            f"| [{cell(_title(ds))}]({slug(ds.name)}.md) | {cell(ds.type)} | "
            f"{year_range(ds.temporal_start, ds.temporal_end)} | {cell(ds.license)} | {cell(description)} |\n"
        )
    return "".join(out)


def _levels(page) -> str:
    levels = sorted({fc.group_level for fc in page.collections if fc.group_level is not None})
    if not levels:
        return "—"
    return f"ADM{levels[0]}" if len(levels) == 1 else f"ADM{levels[0]}–ADM{levels[-1]}"


def boundaries_index(pages) -> str:
    countries = [p for p in pages if p.geoboundaries]
    others = [p for p in pages if not p.geoboundaries]
    out = [
        front_matter(
            f"Boundaries in AidData GeoQuery: administrative boundaries for {len(countries)} "
            f"countries from geoBoundaries, plus {len(others)} other boundary sets."
        ),
        "# Boundaries\n\n",
        "Every set of boundaries you can extract data for in GeoQuery.\n\n",
    ]
    if countries:
        out.append(f"## Countries\n\nAdministrative boundaries from [geoBoundaries]({GEOBOUNDARIES_URL}).\n\n")
        out.append("| Country | Levels |\n|---|---|\n")
        out.extend(f"| [{cell(p.place)}]({p.slug}.md) | {_levels(p)} |\n" for p in countries)
        out.append("\n")
    if others:
        out.append("## Other boundary sets\n\n| Boundaries | Collections | Source |\n|---|---|---|\n")
        out.extend(
            f"| [{cell(p.title)}]({p.slug}.md) | {len(p.collections)} | {cell(p.collections[0].source_name)} |\n"
            for p in others
        )
    return "".join(out)


def redirect_html(target: str) -> str:
    """A stand-in at a moved page's old URL. GitHub Pages has no server-side redirects."""
    t = html.escape(target, quote=True)
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>Moved</title>\n'
        '<meta name="robots" content="noindex">\n'
        f'<meta http-equiv="refresh" content="0; url={t}">\n'
        f'<link rel="canonical" href="{t}">\n'
        f'</head><body><p>This page has moved to <a href="{t}">{t}</a>.</p></body></html>\n'
    )
```

- [ ] **Step 4: Run the tests**

Run: `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_render`
Expected: `OK`.

- [ ] **Step 5: Commit** (only with the user's go-ahead)

```bash
git add backend/datasets/docs/render.py backend/datasets/tests/test_docs_render.py
git commit -m "Render data docs pages for datasets, grouped boundaries and indexes"
```

---

### Task 5: Build, bundle, nightly task and command

**Goal:** `datasets.docs.build` writes every page and an atomic bundle with a manifest. A nightly Celery task, instrumented with `observe_job("data_docs")`, and a `build_data_docs` management command run it.

**Files:**
- Create: `backend/datasets/docs/build.py`, `backend/datasets/management/commands/build_data_docs.py`
- Modify: `backend/datasets/tasks/__init__.py`, `backend/analytics/background_metrics.py:18-19`, `backend/geoquery/settings.py` (`DATA_DOCS_BUNDLE` after `REQUESTS_DIR` at line ~340; beat block lines ~685–721)
- Test: `backend/datasets/tests/test_docs_build.py`

**Acceptance Criteria:**
- [ ] `build_bundle(path)` writes a gzip tarball whose top-level members are exactly `manifest.json`, `datasets`, `boundaries`. The manifest has `generated_at`, `datasets`, `boundary_pages`, `collections` and `redirects`.
- [ ] Each collection's old URL `boundaries/<slug(name)>/index.html` redirects to `../<page>/#<slug(name)>`. No redirect is written where that slug equals a page slug.
- [ ] Two datasets whose names give the same slug raise `GroupingError`.
- [ ] No temporary file is left beside the bundle after a failed build.
- [ ] `JOBS` contains `"data_docs"`, and `CELERY_BEAT_SCHEDULE["build-data-docs"]` runs `datasets.tasks.build_data_docs_task` at 05:00 UTC.
- [ ] `uv run manage.py build_data_docs --out /tmp/x` writes `/tmp/x/datasets/index.md` and `/tmp/x/boundaries/index.md` locally.
- [ ] Tests pass.

**Verify:** `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_build analytics.tests.test_background_metrics` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests**

`backend/datasets/tests/test_docs_build.py`:

```python
import json
import tarfile
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from datasets.docs.build import build_bundle
from datasets.docs.grouping import GroupingError
from datasets.models import Dataset
from features.models import Feature, FeatMap, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin


@override_settings(FRONTEND_BASE_URL="https://app.example")
class BuildBundleTests(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        Dataset.objects.create(name="malaria", path="/malaria", type="raster", title="Malaria",
                               is_global=True, active=True, public=True)
        for level in (0, 1):
            fc = FeatureCollection.objects.create(
                name=f"gB_57dcd43_NPL_ADM{level}", path=f"/npl{level}", group_name="gb_v6_npl",
                group_level=level, group_title="Nepal - GeoBoundaries v6",
                source_name="geoBoundaries", active=True, public=True,
            )
            FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape="POINT(0 0)"))
        self.tmp = Path(tempfile.mkdtemp())
        self.bundle = self.tmp / "docs" / "data-docs.tar.gz"

    def test_bundle_contents_and_manifest(self):
        manifest = build_bundle(self.bundle)

        with tarfile.open(self.bundle) as tar:
            names = tar.getnames()
            self.assertEqual({n.split("/")[0] for n in names}, {"manifest.json", "datasets", "boundaries"})
            self.assertIn("datasets/malaria.md", names)
            self.assertIn("boundaries/gb-npl.md", names)
            stub = tar.extractfile("boundaries/gb-57dcd43-npl-adm1/index.html").read().decode()
            self.assertEqual(json.load(tar.extractfile("manifest.json")), manifest)
        self.assertIn("url=../gb-npl/#gb-57dcd43-npl-adm1", stub)
        self.assertEqual(
            {k: manifest[k] for k in ("datasets", "boundary_pages", "collections", "redirects")},
            {"datasets": 1, "boundary_pages": 1, "collections": 2, "redirects": 2},
        )
        self.assertEqual(list(self.bundle.parent.iterdir()), [self.bundle])

    def test_dataset_slug_collision_is_an_error(self):
        Dataset.objects.create(name="Malaria", path="/Malaria", type="raster", active=True, public=True)
        with self.assertRaises(GroupingError):
            build_bundle(self.bundle)

    def test_failed_build_leaves_no_partial_file(self):
        with mock.patch("datasets.docs.build.tarfile.open", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                build_bundle(self.bundle)
        self.assertEqual(list(self.bundle.parent.iterdir()), [])


class ScheduleTests(TestCase):
    def test_nightly_beat_entry_and_job_metrics(self):
        from analytics.background_metrics import JOBS

        entry = settings.CELERY_BEAT_SCHEDULE["build-data-docs"]
        self.assertEqual(entry["task"], "datasets.tasks.build_data_docs_task")
        self.assertEqual(entry["schedule"].hour, {5})
        self.assertIn("data_docs", JOBS)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_build`
Expected: `ModuleNotFoundError: No module named 'datasets.docs.build'`.

- [ ] **Step 3: Write `backend/datasets/docs/build.py`**

```python
"""Load public datasets and boundaries, write their docs pages, and bundle them.

build_bundle is what the nightly task runs. It writes the tarball the docs
workflow downloads, replacing the previous one atomically so a download never
sees a half-written file.
"""

import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Prefetch

from .coverage import page_coverage
from .grouping import GroupingError, build_pages
from .render import boundaries_index, boundary_page, dataset_page, datasets_index, redirect_html
from .text import slug

MEMBERS = ("datasets", "boundaries")


def load(using="replica"):
    from datasets.models import Dataset, DatasetResource
    from features.models import FeatMap, FeatureCollection

    datasets = list(
        Dataset.objects.using(using).filter(public=True, active=True)
        .prefetch_related(
            Prefetch("resources", queryset=DatasetResource.objects.using(using).order_by("temporal", "name")),
            "mappings",
        )
        .order_by("title", "name")
    )
    collections = list(
        FeatureCollection.objects.using(using).filter(public=True, active=True, is_user_upload=False)
    )
    feature_counts = dict(
        FeatMap.objects.using(using).filter(fc_id__in=[fc.id for fc in collections])
        .values("fc_id").annotate(n=Count("id")).values_list("fc_id", "n")
    )
    return datasets, collections, feature_counts


def write_pages(out_dir, datasets, collections, feature_counts, app_url, coverage=None) -> dict:
    """Replace out_dir/datasets and out_dir/boundaries with freshly generated
    pages, and return the manifest. Nothing else in out_dir is touched."""
    out_dir = Path(out_dir)
    pages = build_pages(collections)
    if coverage is None:
        coverage = page_coverage(pages, datasets)

    dataset_slugs = {}
    for ds in datasets:
        other = dataset_slugs.setdefault(slug(ds.name), ds.name)
        if other != ds.name:
            raise GroupingError(f"datasets {other!r} and {ds.name!r} would share datasets/{slug(ds.name)}/")

    for name in MEMBERS:
        shutil.rmtree(out_dir / name, ignore_errors=True)
        (out_dir / name).mkdir(parents=True)
    ds_dir, bd_dir = out_dir / "datasets", out_dir / "boundaries"

    for ds in datasets:
        available = [(p, coverage[p.slug][ds.id]) for p in pages if ds.id in coverage[p.slug]]
        (ds_dir / f"{slug(ds.name)}.md").write_text(dataset_page(ds, available), encoding="utf-8")
    (ds_dir / "index.md").write_text(datasets_index(datasets), encoding="utf-8")

    by_id = {ds.id: ds for ds in datasets}
    page_slugs = {p.slug for p in pages} | {"index"}
    redirects = 0
    for page in pages:
        covering = sorted(
            ((by_id[ds_id], status) for ds_id, status in coverage[page.slug].items()),
            key=lambda pair: (pair[0].title or pair[0].name).lower(),
        )
        (bd_dir / f"{page.slug}.md").write_text(
            boundary_page(page, covering, feature_counts, app_url), encoding="utf-8"
        )
        for fc in page.collections:
            old = slug(fc.name)
            if old in page_slugs:
                continue
            stub = bd_dir / old / "index.html"
            stub.parent.mkdir(exist_ok=True)
            stub.write_text(redirect_html(f"../{page.slug}/#{old}"), encoding="utf-8")
            redirects += 1
    (bd_dir / "index.md").write_text(boundaries_index(pages), encoding="utf-8")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": len(datasets),
        "boundary_pages": len(pages),
        "collections": len(collections),
        "redirects": redirects,
    }


def build_data_docs(out_dir) -> dict:
    datasets, collections, feature_counts = load()
    return write_pages(out_dir, datasets, collections, feature_counts, settings.FRONTEND_BASE_URL)


def build_bundle(bundle_path=None) -> dict:
    bundle_path = Path(bundle_path or settings.DATA_DOCS_BUNDLE)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pages_dir = Path(tmp) / "pages"
        manifest = build_data_docs(pages_dir)
        (pages_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        fd, partial = tempfile.mkstemp(prefix=".data-docs.", suffix=".tmp", dir=bundle_path.parent)
        try:
            with os.fdopen(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w:gz") as tar:
                for name in ("manifest.json", *MEMBERS):
                    tar.add(pages_dir / name, arcname=name)
            # mkstemp creates 0600; the backend pod serving the file needs to read it.
            os.chmod(partial, 0o664)
            os.replace(partial, bundle_path)
        except BaseException:
            Path(partial).unlink(missing_ok=True)
            raise
    return manifest
```

- [ ] **Step 4: Add the task, the metrics job and the settings**

Replace the `build_dataset_docs_task` function at the top of `backend/datasets/tasks/__init__.py` (keep `ensure_dataset_partitions_task` and `ensure_all_dataset_partitions_task` unchanged):

```python
from celery import shared_task

from analytics.background_metrics import observe_job
from analytics.query_tags import tagged


@shared_task
@observe_job("data_docs")
@tagged("docs.build")
def build_data_docs_task():
    """Nightly: regenerate the data docs pages into the bundle the docs site
    downloads (datasets.docs.build.build_bundle). Returns the manifest."""
    from datasets.docs.build import build_bundle

    return build_bundle()
```

In `backend/analytics/background_metrics.py`, change `JOBS` to:

```python
JOBS = ("extract_sync", "request_sweep", "task_reaper", "error_sweep",
        "request_reaper", "materialize", "boundary_ingest", "data_docs")
```

In `backend/geoquery/settings.py`, directly after the `REQUESTS_DIR = ...` line:

```python
# Generated data docs pages, bundled nightly by datasets.tasks.build_data_docs_task.
# Inside the requests share so the existing /requests/<dir>/<file> rule serves it,
# at <app_url>/requests/docs/data-docs.tar.gz, where the docs workflow downloads it.
DATA_DOCS_BUNDLE = REQUESTS_DIR / "docs" / "data-docs.tar.gz"
```

Then replace the whole comment block in `CELERY_BEAT_SCHEDULE`, from `# Both docs builders are deliberately unscheduled.` through the commented-out `"build-boundary-docs"` entry's closing `# },`, with:

```python
    # Regenerates the data docs bundle (datasets.docs). The docs workflow
    # downloads it at 06:00 UTC, an hour later; see .github/workflows/docs.yml.
    "build-data-docs": {
        "task": "datasets.tasks.build_data_docs_task",
        "schedule": crontab(hour=5, minute=0),
    },
```

- [ ] **Step 5: Write the management command**

`backend/datasets/management/commands/build_data_docs.py`:

```python
from pathlib import Path

from django.core.management.base import BaseCommand

from datasets.docs.build import build_bundle, build_data_docs


class Command(BaseCommand):
    help = (
        "Generate the data documentation pages. With --out, write them into a directory "
        "(for a local docs preview); otherwise write the bundle the docs site downloads."
    )

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group()
        target.add_argument("--out", help="Directory to write datasets/ and boundaries/ into")
        target.add_argument("--bundle", help="Bundle path (default: settings.DATA_DOCS_BUNDLE)")

    def handle(self, *args, **options):
        if options["out"]:
            manifest = build_data_docs(Path(options["out"]))
            where = options["out"]
        else:
            manifest = build_bundle(options["bundle"])
            where = options["bundle"] or "settings.DATA_DOCS_BUNDLE"
        self.stdout.write(self.style.SUCCESS(
            f"{manifest['datasets']} dataset pages, {manifest['boundary_pages']} boundary pages "
            f"({manifest['collections']} collections, {manifest['redirects']} redirects) -> {where}"
        ))
```

- [ ] **Step 6: Run the tests and a local build**

Run: `sudo docker compose exec -T backend uv run manage.py test datasets.tests.test_docs_build analytics.tests.test_background_metrics`
Expected: `OK`.

Run: `sudo docker compose exec -T backend uv run manage.py build_data_docs --out /tmp/data-docs && sudo docker compose exec -T backend ls /tmp/data-docs/datasets/index.md /tmp/data-docs/boundaries/index.md`
Expected: a success line with counts, then both paths listed.

- [ ] **Step 7: Commit** (only with the user's go-ahead)

```bash
git add backend/datasets/docs/build.py backend/datasets/management/commands/build_data_docs.py \
  backend/datasets/tasks/__init__.py backend/analytics/background_metrics.py \
  backend/geoquery/settings.py backend/datasets/tests/test_docs_build.py
git commit -m "Build the data docs bundle nightly into the requests share"
```

---

### Task 6: Remove the old generators

**Goal:** Remove the two old docs generators, their commands, Celery tasks and tests. The one other caller now uses `datasets.docs.text.absolute_url`.

**Files:**
- Delete: `backend/datasets/tasks/create_docs.py`, `backend/features/tasks/create_docs.py`, `backend/datasets/management/commands/build_dataset_docs.py`, `backend/features/management/commands/build_boundary_docs.py`, `backend/datasets/tests/test_create_docs.py`
- Modify: `backend/features/tasks/__init__.py` (remove `build_boundary_docs_task`), `backend/features/tests.py` (remove the `BoundaryDocsPageTests` class at the end), `backend/analytics/tasks/documentation.py:7`

**Acceptance Criteria:**
- [ ] `grep -rn "create_docs\|build_dataset_docs\|build_boundary_docs" backend --include=*.py` prints nothing.
- [ ] `analytics.tests.test_documentation`, `features.tests` and all `datasets` tests pass.

**Verify:** `grep -rn "create_docs\|build_dataset_docs\|build_boundary_docs" backend --include=*.py; sudo docker compose exec -T backend uv run manage.py test analytics.tests.test_documentation features datasets` → no grep output, then `OK`

**Steps:**

- [ ] **Step 1: Delete the old modules, commands and tests**

```bash
git rm backend/datasets/tasks/create_docs.py backend/features/tasks/create_docs.py \
  backend/datasets/management/commands/build_dataset_docs.py \
  backend/features/management/commands/build_boundary_docs.py \
  backend/datasets/tests/test_create_docs.py
```

- [ ] **Step 2: Remove `build_boundary_docs_task`** from `backend/features/tasks/__init__.py`, leaving:

```python
from celery import shared_task


@shared_task
def update_simplified_geometries_task(fc_id):
    """Recompute one collection's simplified-geometry rows on a worker.

    For callers that shouldn't block on simplification; the ingest commands
    call features.matviews.update_simplified_geometries directly instead so
    the update commits atomically with the ingest itself.
    """
    from features.matviews import update_simplified_geometries
    update_simplified_geometries(fc_id)
```

- [ ] **Step 3: Remove the `BoundaryDocsPageTests` class**: everything from `class BoundaryDocsPageTests(TestCase):` to the end of `backend/features/tests.py`, and the two blank lines before it.

- [ ] **Step 4: Repoint the URL helper** in `backend/analytics/tasks/documentation.py`. Replace line 7:

```python
from datasets.tasks.create_docs import _absolute_url
```

with:

```python
from datasets.docs.text import absolute_url as _absolute_url
```

- [ ] **Step 5: Check and run the tests**

Run: `grep -rn "create_docs\|build_dataset_docs\|build_boundary_docs" backend --include=*.py; sudo docker compose exec -T backend uv run manage.py test analytics.tests.test_documentation features datasets`
Expected: no grep output, then `OK`.

- [ ] **Step 6: Commit** (only with the user's go-ahead)

```bash
git add -A backend/features/tasks/__init__.py backend/features/tests.py backend/analytics/tasks/documentation.py
git commit -m "Remove the old dataset and boundary docs generators"
```

---

### Task 7: Ship the backend and produce the first prod bundle

**Goal:** The backend changes are live in prod, a check run against prod data builds cleanly, and `https://geoquery.aiddata.wm.edu/requests/docs/data-docs.tar.gz` serves a valid bundle. Every step that commits, deploys or writes to prod needs the user's explicit go-ahead.

**Files:** none (operational)

**Acceptance Criteria:**
- [ ] Prod serves the new backend version (the deploy has been confirmed live, not just green CI).
- [ ] `build_data_docs --out /tmp/data-docs` in `deploy/geoquery-import` reports about 63 dataset pages and about 230 geoBoundaries country pages plus the other groups, with no `GroupingError`.
- [ ] Those pages, copied into a local checkout, build with `zensical build --clean --strict` with no warnings.
- [ ] `curl -sSf https://geoquery.aiddata.wm.edu/requests/docs/data-docs.tar.gz | tar -tz | head` lists `manifest.json`, `datasets/…` and `boundaries/…`.

**Verify:** `curl -sSf https://geoquery.aiddata.wm.edu/requests/docs/data-docs.tar.gz | tar -xzO manifest.json` → JSON with `datasets` ≥ 40 and `boundary_pages` ≥ 200

**Steps:**

- [ ] **Step 1: Ask the user** whether to commit and push Tasks 2–6 to `main`, and which `[DEPLOY-X.Y.Z]` marker to use (the last was 0.89.3). Push only after they say yes.

- [ ] **Step 2: Confirm the deploy is live.** Flux lags behind CI, so after the deploy workflow succeeds, check the running image:

Run: `kubectl get deploy -n geoquery-prod background-worker -o jsonpath='{.spec.template.spec.containers[0].image}'`
Expected: the tag for the new release.

- [ ] **Step 3: Check run against prod data.** This only reads the replica and writes to the pod's `/tmp`:

```bash
S=/tmp/claude-1000/-home-userx-git/4c0d4449-657c-43bb-9014-88f133b24a01/scratchpad
kubectl exec -n geoquery-prod deploy/geoquery-import -- sh -c 'rm -rf /tmp/data-docs && uv run manage.py build_data_docs --out /tmp/data-docs'
kubectl exec -n geoquery-prod deploy/geoquery-import -- tar cf - -C /tmp/data-docs datasets boundaries > $S/data-docs.tar
kubectl exec -n geoquery-prod deploy/geoquery-import -- rm -rf /tmp/data-docs
```

- [ ] **Step 4: Build the docs locally with those pages.** Do this in a scratch copy, not the repo:

```bash
rm -rf $S/dd && mkdir -p $S/dd && cp -r docs zensical.toml overrides $S/dd/
rm -rf $S/dd/docs/data_documentation/datasets $S/dd/docs/data_documentation/boundaries
tar xf $S/data-docs.tar -C $S/dd/docs/data_documentation
cd $S/dd && uv run --project /home/userx/git/geoquery --only-group docs zensical build --clean --strict
```

Expected: "No issues found". Spot-check `site/data_documentation/boundaries/gb-npl/index.html` for the ADM sections and the datasets table, and `site/data_documentation/boundaries/gb-57dcd43-npl-adm1/index.html` for the redirect.

- [ ] **Step 5: Write the first prod bundle.** This is a prod write, so get the user's explicit go-ahead first:

Run: `kubectl exec -n geoquery-prod deploy/geoquery-import -- uv run manage.py build_data_docs`
Expected: the success line, ending `-> settings.DATA_DOCS_BUNDLE`.

- [ ] **Step 6: Check it's served**

Run: `curl -sSf https://geoquery.aiddata.wm.edu/requests/docs/data-docs.tar.gz | tar -xzO manifest.json`
Expected: the manifest JSON.

---

### Task 8: The docs workflow downloads the bundle; stop committing generated pages

**Goal:** The docs workflow (on push, nightly at 06:00 UTC, and on manual dispatch) downloads, checks and unpacks the bundle before building. The generated directories are removed from git and ignored.

**Files:**
- Create: `.github/scripts/fetch_data_docs.py`, `.github/scripts/test_fetch_data_docs.py`
- Modify: `.github/workflows/docs.yml`, `.gitignore`
- Delete (from git): `docs/data_documentation/datasets/`, `docs/data_documentation/boundaries/`

**Acceptance Criteria:**
- [ ] `fetch_data_docs.py` exits 1 with a `::error::` line, leaving `docs/data_documentation/{datasets,boundaries}` untouched, when the bundle can't be downloaded, isn't a gzip tarball, has no valid `manifest.json`, or has fewer than 40 datasets or 200 boundary pages.
- [ ] It prints a `::warning::` (and still exits 0) when the manifest is more than 3 days old.
- [ ] It extracts only `datasets/` and `boundaries/`, using `filter="data"`.
- [ ] The script's tests pass.
- [ ] `python3 .github/scripts/fetch_data_docs.py && uv run --only-group docs zensical build --clean --strict` succeeds locally against the prod bundle.
- [ ] `git status` shows the two generated directories as deleted, and they're listed in `.gitignore`.

**Verify:** `uv run --only-group docs python -m unittest discover -s .github/scripts -p 'test_*.py' -v` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests**

`.github/scripts/test_fetch_data_docs.py`:

```python
import io
import json
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_data_docs as f  # noqa: E402


def bundle(manifest=None, extra=()):
    manifest = manifest or {"generated_at": datetime.now(timezone.utc).isoformat(),
                            "datasets": 63, "boundary_pages": 235}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        files = {"manifest.json": json.dumps(manifest), "datasets/index.md": "# Datasets\n",
                 "boundaries/gb-npl.md": "# Nepal boundaries\n", **dict(extra)}
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class UnpackTests(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp())
        (self.target / "datasets").mkdir()
        (self.target / "datasets" / "old.md").write_text("old")
        (self.target / "index.md").write_text("hand-written")

    def test_replaces_only_the_generated_directories(self):
        manifest, warnings = f.unpack(bundle(extra={"evil.md": "x"}), self.target)
        self.assertEqual(manifest["datasets"], 63)
        self.assertEqual(warnings, [])
        self.assertTrue((self.target / "boundaries" / "gb-npl.md").exists())
        self.assertFalse((self.target / "datasets" / "old.md").exists())
        self.assertFalse((self.target / "evil.md").exists())
        self.assertEqual((self.target / "index.md").read_text(), "hand-written")

    def test_too_small_bundle_fails_and_touches_nothing(self):
        small = {"generated_at": datetime.now(timezone.utc).isoformat(), "datasets": 3, "boundary_pages": 235}
        with self.assertRaisesRegex(f.BundleError, "3 datasets"):
            f.unpack(bundle(small), self.target)
        self.assertTrue((self.target / "datasets" / "old.md").exists())

    def test_not_a_tarball(self):
        with self.assertRaisesRegex(f.BundleError, "gzip"):
            f.unpack(b"<html>404</html>", self.target)

    def test_missing_manifest(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz"):
            pass
        with self.assertRaisesRegex(f.BundleError, "manifest"):
            f.unpack(buf.getvalue(), self.target)

    def test_stale_bundle_warns(self):
        old = {"generated_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
               "datasets": 63, "boundary_pages": 235}
        _, warnings = f.unpack(bundle(old), self.target)
        self.assertEqual(len(warnings), 1)
        self.assertIn("5 days ago", warnings[0])


class BundleUrlTests(unittest.TestCase):
    def test_url_comes_from_app_url(self):
        config = Path(tempfile.mkdtemp()) / "zensical.toml"
        config.write_text('[project.extra]\napp_url = "https://app.example/"\n')
        self.assertEqual(f.bundle_url(config), "https://app.example/requests/docs/data-docs.tar.gz")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run --only-group docs python -m unittest discover -s .github/scripts -p 'test_*.py' -v`
Expected: `ModuleNotFoundError: No module named 'fetch_data_docs'`.

- [ ] **Step 3: Write `.github/scripts/fetch_data_docs.py`**

```python
"""Download the generated data docs pages into docs/data_documentation.

The pages are generated nightly in the cluster (datasets.tasks.build_data_docs_task
in the backend), which writes a bundle into the requests share. The app serves it
at <app_url>/requests/docs/data-docs.tar.gz, with app_url read from zensical.toml.

Exits 1 when the bundle is missing, unreadable or much smaller than expected,
before touching anything, so a bad night never replaces the live docs. Warns
when the bundle is stale, which means the nightly task has stopped.

Usage: python3 .github/scripts/fetch_data_docs.py [bundle-url]
"""

import io
import json
import shutil
import sys
import tarfile
import tomllib
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "docs" / "data_documentation"
MEMBERS = ("datasets", "boundaries")
MIN_DATASETS = 40
MIN_BOUNDARY_PAGES = 200
STALE_AFTER = timedelta(days=3)


class BundleError(Exception):
    pass


def bundle_url(config=REPO / "zensical.toml") -> str:
    with open(config, "rb") as fh:
        app_url = tomllib.load(fh)["project"]["extra"]["app_url"]
    return app_url.rstrip("/") + "/requests/docs/data-docs.tar.gz"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "geoquery-docs-build"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except OSError as exc:
        raise BundleError(f"could not download {url}: {exc}") from exc


def check_manifest(manifest: dict, now=None) -> list:
    """Raise BundleError if the bundle is too small; return any warnings."""
    datasets, pages = manifest.get("datasets", 0), manifest.get("boundary_pages", 0)
    if datasets < MIN_DATASETS or pages < MIN_BOUNDARY_PAGES:
        raise BundleError(
            f"bundle has {datasets} datasets and {pages} boundary pages; "
            f"expected at least {MIN_DATASETS} and {MIN_BOUNDARY_PAGES}"
        )
    generated = datetime.fromisoformat(manifest["generated_at"])
    age = (now or datetime.now(timezone.utc)) - generated
    if age > STALE_AFTER:
        return [f"bundle was generated {age.days} days ago ({manifest['generated_at']}); "
                "is build_data_docs_task running?"]
    return []


def unpack(data: bytes, target: Path):
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as exc:
        raise BundleError(f"not a gzip tarball: {exc}") from exc
    with tar:
        try:
            manifest = json.load(tar.extractfile("manifest.json"))
        except (KeyError, TypeError, ValueError) as exc:
            raise BundleError(f"bundle has no valid manifest.json: {exc}") from exc
        warnings = check_manifest(manifest)
        members = [m for m in tar.getmembers() if m.name.split("/")[0] in MEMBERS]
        for name in MEMBERS:
            shutil.rmtree(target / name, ignore_errors=True)
        tar.extractall(target, members=members, filter="data")
    return manifest, warnings


def main(argv) -> int:
    url = argv[1] if len(argv) > 1 else bundle_url()
    try:
        manifest, warnings = unpack(download(url), TARGET)
    except BundleError as exc:
        print(f"::error::{exc}")
        return 1
    for warning in warnings:
        print(f"::warning::{warning}")
    print(f"Unpacked {manifest['datasets']} dataset pages and {manifest['boundary_pages']} "
          f"boundary pages generated {manifest['generated_at']} from {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run the tests**

Run: `uv run --only-group docs python -m unittest discover -s .github/scripts -p 'test_*.py' -v`
Expected: `OK`.

- [ ] **Step 5: Update the docs workflow.** In `.github/workflows/docs.yml`, change the trigger block to:

```yaml
on:
  push:
    branches:
      - main
      - dev
      - sgoodm
      - jwhall
    paths:
      - docs/**
      - zensical.toml
      - overrides/**
      - pyproject.toml
      - uv.lock
      - .github/workflows/docs.yml
      - .github/scripts/**
  # The data pages are regenerated in the cluster at 05:00 UTC
  # (build-data-docs in the backend's beat schedule); pick them up an hour later.
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:
```

In the `build` job, replace the single `- run: uv run --only-group docs zensical build --clean --strict` step with:

```yaml
      - name: Test the data docs fetch script
        run: uv run --only-group docs python -m unittest discover -s .github/scripts -p 'test_*.py'
      # The dataset and boundary pages aren't in git: they're generated nightly
      # in the cluster and served by the app. Fails rather than build without them.
      - name: Fetch generated data pages
        run: uv run --only-group docs python .github/scripts/fetch_data_docs.py
      - run: uv run --only-group docs zensical build --clean --strict
```

The fetch step comes after "Set app URL", so a `GEOQUERY_APP_URL` override also changes where the bundle comes from. Scheduled and manual runs use `main`, so the `deploy` job's `github.ref == 'refs/heads/main'` condition already lets them publish.

- [ ] **Step 6: Stop tracking the generated pages.** Append to `.gitignore`:

```gitignore

# Generated nightly in the cluster and fetched by the docs workflow
# (.github/scripts/fetch_data_docs.py); run that script to preview locally.
/docs/data_documentation/datasets/
/docs/data_documentation/boundaries/
```

Then run:

```bash
git rm -r --cached -q docs/data_documentation/datasets docs/data_documentation/boundaries
```

- [ ] **Step 7: Build locally against the prod bundle** (requires Task 7)

Run: `uv run --only-group docs python .github/scripts/fetch_data_docs.py && uv run --only-group docs zensical build --clean --strict`
Expected: the "Unpacked …" line, then "No issues found".

- [ ] **Step 8: Commit and push** (only with the user's go-ahead; no deploy marker, since this is docs and CI only)

```bash
git add .github/scripts .github/workflows/docs.yml .gitignore
git commit -m "Build the docs from the nightly data docs bundle instead of committed pages"
```

After pushing, watch the docs run on `main`. Both jobs should succeed, and `https://docs.geoquery.org/data_documentation/boundaries/gb-npl/` should serve the Nepal page.
