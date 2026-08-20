# STAC API docs + demo notebook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `docs/using-geoquery/tutorials/stac-api-demo.ipynb`, a living notebook walking every `/api/stac/v1/` endpoint against a real running server, including a `pystac-client` interop section, linked from the tutorials index.

**Architecture:** Mirrors the existing `public-api-demo.ipynb` precedent — one markdown-cell-explains / code-cell-calls pair per endpoint, chaining real ids resolved from earlier cells rather than hardcoding them, `requests` throughout plus a closing `pystac-client` section demonstrating real STAC-ecosystem interoperability. No application code changes — this is documentation-only work on top of the already-shipped, already-reviewed `stac_api` Phase 1.

**Tech Stack:** Jupyter notebook (nbformat 4), `requests` (already available), new dependency `pystac-client` added to the `notebooks` uv group.

**User decisions (already made):**
- Minimal docs footprint matching `public_api`'s precedent — a notebook plus one `tutorials/index.md` link, no separate written "what is STAC" page.
- Include a `pystac-client` section demonstrating real third-party STAC-client interop, not just `requests` calls.

---

## Reference: design spec

`docs/superpowers/specs/2026-08-20-stac-docs-notebook-design.md` — read this first for the *why* behind the notebook's structure. This plan implements it.

---

### Task 1: Add `pystac-client` dependency

**Goal:** `pystac-client` importable in the project's `.venv`, alongside the existing `notebooks` group deps (`ipykernel`).

**Files:**
- Modify: `pyproject.toml` (repo root)

**Acceptance Criteria:**
- [ ] `pystac-client` appears in the `notebooks` dependency-group in root `pyproject.toml`
- [ ] `uv.lock` is regenerated and includes `pystac-client` and its transitive deps (`pystac`, `python-dateutil`, etc.)
- [ ] `import pystac_client` succeeds in the project's `.venv`

**Verify:** `uv run python -c "import pystac_client; print(pystac_client.__version__)"` → prints a version string, no error

**Steps:**

- [ ] **Step 1: Add the dependency**

Read root `pyproject.toml`'s current `[dependency-groups]` section first (it should show `docs`, `notebooks`, and `test` groups after the STAC API plan's Task 8). Add `pystac-client` to the `notebooks` group:

```toml
[dependency-groups]
docs = ["zensical~=0.0.43"]
notebooks = ["ipykernel>=6.29", "pystac-client>=0.9"]
test = ["stac-pydantic>=3.0"]
```

(Only the `notebooks` line changes — `docs` and `test` stay exactly as they are. If the file's current content differs from this in any way beyond the `notebooks` line, that's fine — leave everything else untouched and only add `pystac-client` to whatever `notebooks` already contains.)

- [ ] **Step 2: Lock and sync**

From the repo root, on the host:
```bash
uv lock
uv sync
```
Expected: `uv.lock` updates to include `pystac-client` (and transitively `pystac`, `python-dateutil`, `ciso8601` or similar) with no version conflicts.

- [ ] **Step 3: Verify**

Run: `uv run python -c "import pystac_client; print(pystac_client.__version__)"`
Expected: prints a version string (e.g. `0.9.0` or similar), no `ModuleNotFoundError`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "Add pystac-client to the notebooks dependency group"
```

---

### Task 2: Write the demo notebook and link it from the tutorials index

**Goal:** `docs/using-geoquery/tutorials/stac-api-demo.ipynb` walking every `stac_api` endpoint plus a `pystac-client` interop section, verified to actually run end-to-end against the live dev server, linked from `docs/using-geoquery/tutorials/index.md`.

**Files:**
- Create: `docs/using-geoquery/tutorials/stac-api-demo.ipynb`
- Modify: `docs/using-geoquery/tutorials/index.md`

**Acceptance Criteria:**
- [ ] Notebook has markdown cells explaining each endpoint and code cells calling it, in the order: setup → landing page → conformance → browse collections → get a collection → browse items → get an item → boundary collection's synthetic item → search (no params, bbox-filtered GET, equivalent POST) → `pystac-client` interop → closing note
- [ ] Every code cell's logic runs without error against the real running dev server (verified by extracting and running the cell bodies as a plain script, not just eyeballing the JSON)
- [ ] `tutorials/index.md` has a new bullet linking to the notebook, matching the existing Public API demo bullet's format

**Verify:** the extracted-cells verification script (Step 3 below) runs to completion with no exceptions and prints sensible output for every section

**Steps:**

- [ ] **Step 1: Confirm the dev server has real data to demo against**

The `stac_api` app was built and reviewed against a live dev server that already has real Datasets and FeatureCollections (verified during the STAC API plan's final review: 8 active+public Datasets, 8 active+public FeatureCollections). Confirm this is still the case:

```bash
sudo docker compose exec -T backend uv run python manage.py shell -c "
from datasets.models import Dataset
from features.models import FeatureCollection
print('datasets:', Dataset.objects.filter(active=True, public=True).count())
print('feature collections:', FeatureCollection.objects.filter(active=True, public=True).count())
"
```
Expected: both counts > 0. If either is 0, stop and report back — the notebook's "skip if empty" branches will still work, but the demo will be much less useful, and you should flag this to the coordinator rather than proceeding silently.

- [ ] **Step 2: Build the notebook**

Write a one-off Python script (not committed — delete it after Step 4) that constructs the notebook as plain nbformat-4 JSON and writes it to disk. This avoids hand-typing JSON escaping by hand and avoids adding a new dependency (`nbformat`) just to build one file.

Create `/tmp/build_stac_notebook.py`:

```python
import json

def md(source):
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source):
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


cells = [
    md("""# GeoQuery STAC API — Demo

A living walkthrough of every endpoint under `/api/stac/v1/`, GeoQuery's
STAC (SpatioTemporal Asset Catalog) discovery API. Re-run this notebook
against a running GeoQuery dev server to see the API respond for real —
as endpoints are added or change shape, update the matching cell here
rather than letting this drift out of sync."""),
    md("""## 1. Setup

Assumes the GeoQuery dev stack is running locally (`docker compose up -d`)
so the backend is reachable at `localhost:8000`. Point `BASE_URL` elsewhere
to hit a different environment."""),
    code("""%pip install requests pystac-client -q

import json

import requests

BASE_URL = "http://localhost:8000/api/stac/v1"


def call(method, path, **kwargs):
    \"\"\"Make a request and print status + pretty-printed JSON body.\"\"\"
    response = requests.request(method, f"{BASE_URL}{path}", **kwargs)
    print(f"{method} {path} -> {response.status_code}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2)[:2000])
        return data
    except ValueError:
        print(response.text[:500])
        return None"""),
    md("""## 2. Landing page

`GET /` — the STAC Catalog / OGC API landing page. Lists the catalog's
`conformsTo` classes and the `links` a client follows to discover
collections, search, and documentation."""),
    code("""landing = call("GET", "/")
print(f"\\nconforms to {len(landing['conformsTo'])} classes")
print("links:", [link["rel"] for link in landing["links"]])"""),
    md("""## 3. Conformance

`GET /conformance/` — the same `conformsTo` list as the landing page, on
its own endpoint. This is how a client checks what a catalog supports
before trying to use it (e.g. "does this catalog support Item Search?")."""),
    code("""call("GET", "/conformance/")"""),
    md("""## 4. Browse collections

`GET /collections/` — every active, public Dataset *and* FeatureCollection
(boundary set) in GeoQuery, as STAC Collections. Both kinds are mixed
together in one list — there's no separate "boundaries" endpoint here,
unlike the GeoQuery-native public API."""),
    code("""collections_response = call("GET", "/collections/")
collections = collections_response["collections"]
print(f"\\n{len(collections)} collection(s) available")"""),
    md("""## 5. Get a collection by id

`GET /collections/{name}/` — full detail for one collection, including its
spatial/temporal extent and (for boundary sets) `summaries`."""),
    code("""if collections:
    collection_id = collections[0]["id"]
    call("GET", f"/collections/{collection_id}/")
else:
    print("No collections in this environment yet — skipping.")"""),
    md("""## 6. Browse items in a collection

`GET /collections/{name}/items/` — the Items under a collection. For a
dataset-backed collection this is one Item per `DatasetResource` (e.g.
one per year of a time series), paginated via `limit`/`offset` with a
`next` link when more remain."""),
    code("""# Collections without "summaries" are Dataset-backed (only boundary sets
# get summaries) — pick one of those specifically so the items walkthrough
# below shows real DatasetResource items, not the single synthetic one.
dataset_collection = next((c for c in collections if "summaries" not in c), None)
if dataset_collection:
    dataset_collection_id = dataset_collection["id"]
    items_response = call("GET", f"/collections/{dataset_collection_id}/items/")
    items = items_response["features"]
    print(
        f"\\n{items_response['numberMatched']} matched, "
        f"{items_response['numberReturned']} returned"
    )
else:
    items = []
    dataset_collection_id = None
    print("No dataset-backed collections in this environment yet — skipping.")"""),
    md("""## 7. Get an item by id

`GET /collections/{name}/items/{item_id}/` — a single Item. The `via`
link is how a discoverer gets from metadata to actually requesting this
data through GeoQuery — this API deliberately doesn't serve raw files
itself (see the design spec's "no downloadable assets" decision)."""),
    code("""if items:
    item_id = items[0]["id"]
    item = call("GET", f"/collections/{dataset_collection_id}/items/{item_id}/")
    via_link = next(link for link in item["links"] if link["rel"] == "via")
    print(f"\\nvia: {via_link['href']}")
else:
    item = None
    print("No items in this environment yet — skipping.")"""),
    md("""## 8. A boundary set's synthetic item

Boundaries (`FeatureCollection`s) are Collections too, but they get
exactly *one* Item each, not one per administrative unit — a boundary
set is distributed as a single file, not a time series, and individual
`Feature` rows carry no metadata beyond geometry. Its id is always
`{collection_id}-item`."""),
    code("""boundary_collection = next((c for c in collections if "summaries" in c), None)
if boundary_collection:
    boundary_id = boundary_collection["id"]
    boundary_items = call("GET", f"/collections/{boundary_id}/items/")
    print(f"\\n{len(boundary_items['features'])} item(s) — should always be exactly 1")
    print("item id:", boundary_items["features"][0]["id"])
else:
    print("No boundary-backed collections in this environment yet — skipping.")"""),
    md("""## 9. Search

`GET`/`POST /search/` — cross-collection Item search, filtered by `bbox`,
`datetime` (RFC3339, `start/end`, or `..` for open-ended), `collections`,
and `limit`. Both GET (query params) and POST (JSON body) accept the same
filters and return the same shape."""),
    code("""all_items = call("GET", "/search/")
print(f"\\n{all_items['numberMatched']} item(s) across the whole catalog")"""),
    code("""if item and item.get("bbox"):
    xmin, ymin, xmax, ymax = item["bbox"]
    bbox_param = f"{xmin},{ymin},{xmax},{ymax}"
    filtered = call(
        "GET",
        "/search/",
        params={"bbox": bbox_param, "collections": dataset_collection_id},
    )
    print(
        f"\\n{filtered['numberMatched']} item(s) matching bbox={bbox_param} "
        f"in collection {dataset_collection_id}"
    )
else:
    filtered = None
    print("No item bbox available to filter on — skipping.")"""),
    code("""if item and item.get("bbox"):
    post_filtered = call(
        "POST",
        "/search/",
        json={"bbox": item["bbox"], "collections": [dataset_collection_id]},
    )
    print(f"\\nGET and POST agree: {filtered['numberMatched'] == post_filtered['numberMatched']}")
else:
    print("Skipped — no bbox available (see previous cell).")"""),
    md("""## 10. Real STAC client interop

Everything above used raw `requests` to show the exact JSON shape. This
section instead uses `pystac-client` — a real, independently-maintained
STAC client library — talking to this catalog. A hand-rolled server is
exactly as interoperable as a purpose-built one as long as it's genuinely
spec-conformant, which is what this section demonstrates concretely."""),
    code("""from pystac_client import Client

catalog = Client.open(BASE_URL)
print(f"Opened catalog: {catalog.title}")

pystac_collections = list(catalog.get_collections())
print(f"\\n{len(pystac_collections)} collection(s) via pystac-client")
if pystac_collections:
    print("first collection:", pystac_collections[0].id, "-", pystac_collections[0].title)"""),
    code("""search = catalog.search(
    collections=[dataset_collection_id] if dataset_collection_id else None,
    max_items=5,
)
found_items = list(search.item_collection())
print(f"{len(found_items)} item(s) via pystac-client search")
for found_item in found_items:
    print(" -", found_item.id, found_item.datetime)"""),
    md("""## Keeping this notebook current

When an endpoint is added, removed, or changes shape in `backend/stac_api/`,
update the matching section above in the same PR — treat this notebook as
part of the STAC API's contract, not an afterthought. `/api/stac/v1/schema/`
is the source of truth if this notebook and the real API ever disagree."""),
]

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "pygments_lexer": "ipython3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

with open("docs/using-geoquery/tutorials/stac-api-demo.ipynb", "w") as f:
    json.dump(notebook, f, indent=1)
    f.write("\n")

print("wrote docs/using-geoquery/tutorials/stac-api-demo.ipynb")
```

Run it from the repo root: `uv run python /tmp/build_stac_notebook.py`
Expected: `wrote docs/using-geoquery/tutorials/stac-api-demo.ipynb`, no traceback.

- [ ] **Step 3: Verify every code cell actually runs against the live server**

Rather than requiring `nbconvert`/notebook-execution tooling (not currently a project dependency), extract the code cells' source and run them as a plain script — this exercises the exact same logic against the exact same live server, just without the Jupyter kernel wrapper. Skip the `%pip install` magic line (not valid outside a Jupyter kernel; Task 1 already installed the deps into the project's `.venv`).

Create a temporary verification script `/tmp/verify_stac_notebook.py`:

```python
import json

with open("docs/using-geoquery/tutorials/stac-api-demo.ipynb") as f:
    nb = json.load(f)

code_source = []
for cell in nb["cells"]:
    if cell["cell_type"] != "code":
        continue
    source = "".join(cell["source"])
    lines = [line for line in source.splitlines() if not line.startswith("%pip")]
    code_source.append("\n".join(lines))

script = "\n\n".join(code_source)
with open("/tmp/stac_notebook_extracted.py", "w") as f:
    f.write(script)

print(f"extracted {len(code_source)} code cells")
```

Run: `uv run python /tmp/verify_stac_notebook.py`, then run the extracted script itself: `uv run python /tmp/stac_notebook_extracted.py`

Expected: the extracted script runs top to bottom with no traceback, and prints sensible output for every section — actual dataset/collection/item ids and counts from the real dev server, not placeholders. If any section prints a "skipping" message because a resource type isn't present in the current dev data (e.g. no boundary-backed collections), that's fine as long as it's a genuine "not present" case (confirmed via Step 1's counts) rather than a bug. If anything raises an exception, fix the corresponding cell's code in the notebook JSON (re-run Step 2's build script after editing the Python source in `build_stac_notebook.py`, don't hand-edit the `.ipynb` JSON directly) and re-verify.

Delete both temp scripts once verification passes: `rm /tmp/build_stac_notebook.py /tmp/verify_stac_notebook.py /tmp/stac_notebook_extracted.py`

- [ ] **Step 4: Link it from the tutorials index**

`docs/using-geoquery/tutorials/index.md` — current content:
```markdown
# Tutorials

Step-by-step guides and worked examples for getting the most out of GeoQuery.

For video tutorials and research application examples, visit [aiddata.org/geo](https://aiddata.org/geo).

## Available tutorials

- [Public API demo](public-api-demo.ipynb) — a runnable notebook walking through every `/api/public/v1/` endpoint, kept up to date as the API changes.

*More tutorials coming soon. Check back or visit [aiddata.org/geo](https://aiddata.org/geo) for the latest resources.*
```

Add one bullet directly below the existing Public API demo line:
```markdown
# Tutorials

Step-by-step guides and worked examples for getting the most out of GeoQuery.

For video tutorials and research application examples, visit [aiddata.org/geo](https://aiddata.org/geo).

## Available tutorials

- [Public API demo](public-api-demo.ipynb) — a runnable notebook walking through every `/api/public/v1/` endpoint, kept up to date as the API changes.
- [STAC API demo](stac-api-demo.ipynb) — a runnable notebook walking through every `/api/stac/v1/` endpoint, including a real STAC-client (`pystac-client`) interop example, kept up to date as the API changes.

*More tutorials coming soon. Check back or visit [aiddata.org/geo](https://aiddata.org/geo) for the latest resources.*
```

- [ ] **Step 5: Commit**

```bash
git add docs/using-geoquery/tutorials/stac-api-demo.ipynb docs/using-geoquery/tutorials/index.md
git commit -m "Add STAC API demo notebook"
```

---

## Self-review notes

- **Spec coverage:** every section of `2026-08-20-stac-docs-notebook-design.md` maps to Task 2's notebook structure (12 numbered sections in the spec → 10 numbered sections + setup + closing in the actual cell list, since the spec's "search" step (10) covers 3 code cells here — no gap, just the spec described it as one numbered step covering multiple cells, consistent with how the spec itself phrased "one cell with no params... one with a bbox/datetime/collections filter... and one showing the POST form").
- **Placeholder scan:** none — every cell has real, complete source; the build script is a complete, runnable Python file, not pseudocode.
- **Type consistency:** `dataset_collection_id`/`item`/`collections`/`items` variable names are used identically across the cells that reference them (search cells reuse `item`/`dataset_collection_id` exactly as defined in the "browse items"/"get an item" cells above them).
- **Discovered during planning, not a task-blocking issue:** `/search/` has no `next`-link pagination (only `limit`-based truncation) — a client requesting more items than exist under `limit` gets a silently truncated result with no way to page further via standard STAC "follow next" semantics. This is existing, already-shipped, already-reviewed `stac_api` behavior (the design spec never required search pagination, only `limit`), out of scope to change here since this plan is documentation-only. The notebook's `pystac-client` section uses `max_items=5` specifically to stay well within any single page, so it won't surface this gap in the demo itself. Worth a note in project memory for whoever picks up further STAC work.
