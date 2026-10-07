# Legacy Request Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import completed requests from the previous version of GeoQuery into a separate `LegacyRequest` table, and surface them through the existing past-request mechanisms as a collapsed, visually-marked archive section.

**Architecture:** A standalone `LegacyRequest` model keeps legacy rows out of the completion sweep, task materialization and the extract workers by construction rather than by filter. Parallel API endpoints mirror the three existing ones instead of changing their bare-array payloads, which the MCP server also consumes. The Mongo ObjectId is preserved as the primary key behind its own frontend route, leaving the existing `[id=uuid]` param matcher untouched.

**Tech Stack:** Django 5 + DRF, PostGIS, `pyarrow` (already a backend dependency), SvelteKit (Svelte 5 runes), Tailwind, shadcn-svelte.

**User decisions (already made):**
- Import completed requests only (`status == 1`) — failed legacy requests are out of scope.
- Skip any request with empty contact, empty boundary, or zero datasets.
- Preserve the Mongo ObjectId as the primary key; use a separate `/requests/legacy/[id]` route rather than relaxing the UUID matcher.
- Parallel API endpoints (option A), not a changed response shape and not a UNION endpoint.
- Legacy requests appear in all three ownership paths: magic-link history, signed-in My Requests, and user-FK claims.
- Re-runnable upsert with a required `--submitted-before` cutoff; run once now against a fixed date and again at cutover.
- Zip downloads only, at `<base>/<request_id>.zip`, from a base URL supplied later.
- Stats count legacy requests but report them separately.
- Detail page shows summary plus dataset/boundary names — no mapping to current catalog entities.

**Spec:** `docs/superpowers/specs/2026-10-07-legacy-request-migration-design.md`

---

## Execution environment

Per `AGENTS.md`, the `db` service publishes no port to the host, so every `manage.py` command — including tests — must run inside the `backend` container.

**Docker on this machine requires `sudo`.** The invoking user is not in the `docker` group, so an unprefixed `docker compose` fails with `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`. Every command below is therefore `sudo docker compose ...`, and `sudo` is passwordless here.

Bring the stack up first — it is not running by default:

```bash
sudo docker compose up -d
sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests -v 2
```

There is no CI workflow that runs the test suite (`.github/workflows/` holds only build, deploy and docs), so these verify commands are the only gate. Do not substitute host-only `uv run` invocations for the DB-backed tests — they cannot reach the database and will error on connection, not on logic.

Frontend checks run in the `frontend` container:

```bash
sudo docker compose exec frontend bun run check
```

## File structure

**Backend — created:**

| File | Responsibility |
| --- | --- |
| `backend/analytics/migrations/0031_legacyrequest.py` | Schema for `legacy_requests` |
| `backend/analytics/management/commands/import_legacy_requests.py` | Parquet → `LegacyRequest` upsert |
| `backend/analytics/tests/test_legacy_requests.py` | Model, `legacy_requests_for_user`, `legacy_request_links` |
| `backend/analytics/tests/test_import_legacy_requests.py` | Command: filters, skips, idempotency, truncation |
| `backend/analytics/tests/test_legacy_api.py` | The three endpoints |

**Backend — modified:**

| File | Change |
| --- | --- |
| `backend/analytics/models.py` | `LegacyRequest` model |
| `backend/analytics/services.py` | `legacy_requests_for_user`, `legacy_request_links` |
| `backend/analytics/views.py` | Three views |
| `backend/analytics/urls.py` | Three routes |
| `backend/accounts/claims.py` | Claim legacy rows alongside `Request` |
| `backend/accounts/tests.py` | Claim coverage for legacy rows |
| `backend/geoquery/settings.py` | `LEGACY_DOWNLOAD_BASE_URL` |
| `backend/stats/builder.py` | `legacy_request_count` in the snapshot |
| `docker-compose.yml` | Pass `LEGACY_DOWNLOAD_BASE_URL` into the `backend` service |

**Frontend — created:**

| File | Responsibility |
| --- | --- |
| `frontend/src/routes/requests/legacy/[id]/+page.svelte` | Legacy detail page |

**Frontend — modified:**

| File | Change |
| --- | --- |
| `frontend/src/lib/api.ts` | `LegacyPastRequest`, `LegacyRequestDetail`, three fetchers, stats field |
| `frontend/src/routes/requests/[[token]]/+page.svelte` | Collapsed archive section |
| `frontend/src/routes/stats/+page.svelte` | Historical count tile |

Task order follows the dependency chain: model → services → claims → command → API → frontend → stats.

---

### Task 1: LegacyRequest model and migration

**Goal:** The `legacy_requests` table exists with the fields, indexes and constraints the spec defines.

**Files:**
- Modify: `backend/analytics/models.py` (append after `RequestMap`, around line 386)
- Create: `backend/analytics/migrations/0031_legacyrequest.py` (generated; latest existing is `0030_extracttaskbuildrun_worker_tracking.py`)
- Create: `backend/analytics/tests/test_legacy_requests.py`

**Acceptance Criteria:**
- [ ] `LegacyRequest` is creatable with a 24-character ObjectId primary key
- [ ] `dataset_titles` round-trips a list of strings
- [ ] `user` is nullable and set to NULL when the user is deleted
- [ ] The functional index on `Lower("contact")` exists in the migration
- [ ] `makemigrations --check` reports no further changes

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `backend/analytics/tests/test_legacy_requests.py`:

```python
import secrets
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from analytics.models import LegacyRequest

User = get_user_model()

OID = "58c9be24c15e00b8f9fadc1c"


def make_legacy(**overrides):
    """A valid LegacyRequest, overridable per test.

    The id defaults to a fresh ObjectId-shaped value so a test can create
    several rows without having to invent ids; pass `id=` when the test
    asserts on the value itself.
    """
    fields = {
        "id": secrets.token_hex(12),
        "contact": "alice@example.com",
        "custom_name": "Request 03-15-17 18:20",
        "submit_time": datetime(2017, 3, 15, 18, 20, tzinfo=dt_timezone.utc),
        "complete_time": datetime(2017, 3, 15, 20, 15, tzinfo=dt_timezone.utc),
        "boundary_title": "Tanzania ADM3 Boundary - GADM 2.8",
        "boundary_name": "tza_adm3_gadm28",
        "boundary_group": "tza_gadm28",
        "dataset_titles": ["World Bank Geocoded Aid Data v1.4.1", "Population (GPW V4)"],
        "dataset_count": 2,
        "data": {"release_data": [], "raster_data": []},
    }
    fields.update(overrides)
    return LegacyRequest.objects.create(**fields)


class LegacyRequestModelTests(TestCase):
    def test_creates_with_objectid_primary_key(self):
        obj = make_legacy(id=OID)
        obj.refresh_from_db()
        self.assertEqual(obj.pk, OID)
        self.assertEqual(obj.dataset_count, 2)

    def test_dataset_titles_round_trip(self):
        obj = make_legacy()
        obj.refresh_from_db()
        self.assertEqual(
            obj.dataset_titles,
            ["World Bank Geocoded Aid Data v1.4.1", "Population (GPW V4)"],
        )

    def test_user_is_nulled_when_user_deleted(self):
        user = User.objects.create_user(username="alice", email="alice@example.com")
        obj = make_legacy(user=user)
        user.delete()
        obj.refresh_from_db()
        self.assertIsNone(obj.user)

    def test_str_includes_name(self):
        self.assertIn("Request 03-15-17 18:20", str(make_legacy()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests -v 2`
Expected: FAIL — `ImportError: cannot import name 'LegacyRequest' from 'analytics.models'`

- [ ] **Step 3: Add the model**

In `backend/analytics/models.py`, append after the `RequestMap` class. `ArrayField`, `models` and `Lower` are already imported at the top of this file — do not re-import them.

```python
class LegacyRequest(models.Model):
    """A completed request from the previous version of GeoQuery.

    Imported read-only by ``import_legacy_requests``. Deliberately a separate
    table rather than a flag on ``Request``: legacy rows must never reach the
    completion sweep, priority bumping, task materialization, ``RequestMap`` or
    the extract workers, and a separate table makes that true by construction
    instead of by a filter every one of those paths has to remember.

    Only completed requests are imported, so there is no status column -- the
    API reports "completed" for every row. ``prepare_time`` and
    ``process_time`` are not carried over: in 9,716 of the exported completed
    rows they precede ``submit_time``, so importing them would publish a
    timeline that contradicts itself.
    """

    # Mongo ObjectId hex from the old system, preserved so old references and
    # the copied zip filenames keep resolving.
    id = models.CharField(max_length=24, primary_key=True)
    contact = models.CharField(max_length=100)
    custom_name = models.CharField(max_length=100)
    submit_time = models.DateTimeField()
    complete_time = models.DateTimeField()

    boundary_title = models.CharField(max_length=100)
    boundary_name = models.CharField(max_length=64)
    boundary_group = models.CharField(max_length=32)

    # Denormalized for display so neither the list nor the detail endpoint has
    # to parse `data`. Release entries first, then raster.
    dataset_titles = ArrayField(models.CharField(max_length=200), default=list)
    dataset_count = models.SmallIntegerField(default=0)

    # release_data + raster_data verbatim, for provenance.
    data = models.JSONField()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="legacy_requests",
        db_column="user_id",
    )
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "legacy_requests"
        indexes = [
            # Ownership lookups match contact case-insensitively, mirroring
            # requests_contact_lower_idx on Request.
            models.Index(Lower("contact"), name="legacy_contact_lower_idx"),
            # fields= is required here: Index's positional args are
            # *expressions, so a bare "-submit_time" raises models.E012.
            models.Index(fields=["-submit_time"], name="legacy_submit_time_idx"),
        ]

    def __str__(self):
        return f"LegacyRequest {self.id}: {self.custom_name or 'unnamed'}"
```

- [ ] **Step 4: Generate the migration**

Run: `sudo docker compose exec backend uv run python manage.py makemigrations analytics`
Expected: `Create model LegacyRequest` plus the two indexes.

- [ ] **Step 5: Apply and confirm the test passes**

Run:
```bash
sudo docker compose exec backend uv run python manage.py migrate analytics
sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests -v 2
sudo docker compose exec backend uv run python manage.py makemigrations --check --dry-run
```
Expected: migrate OK; 4 tests pass; `makemigrations --check` reports no changes.

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/models.py backend/analytics/migrations/ backend/analytics/tests/test_legacy_requests.py
git commit -m "Add LegacyRequest model for pre-2026 request import"
```

---

### Task 2: Download links and the LEGACY_DOWNLOAD_BASE_URL setting

**Goal:** `legacy_request_links()` returns a zip URL when the base URL is configured and nothing when it is not, so the feature ships before the archive is hosted.

**Files:**
- Modify: `backend/geoquery/settings.py:322` (beside `DOWNLOAD_BASE_URL`)
- Modify: `backend/analytics/services.py` (after `request_links`, ~line 598)
- Modify: `backend/analytics/tests/test_legacy_requests.py`
- Modify: `docker-compose.yml` (the `backend` service's `environment` block)

**Acceptance Criteria:**
- [ ] Unset or empty `LEGACY_DOWNLOAD_BASE_URL` yields `{}` — no `download_url` key at all
- [ ] A configured base yields `{"download_url": "<base>/<id>.zip"}`
- [ ] A trailing slash on the base does not produce a double slash

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `backend/analytics/tests/test_legacy_requests.py`:

```python
from django.test import override_settings

from analytics.services import legacy_request_links


class LegacyRequestLinksTests(TestCase):
    @override_settings(LEGACY_DOWNLOAD_BASE_URL="")
    def test_no_links_when_base_url_unset(self):
        self.assertEqual(legacy_request_links(make_legacy()), {})

    @override_settings(LEGACY_DOWNLOAD_BASE_URL="https://archive.example.com/legacy")
    def test_download_url_when_configured(self):
        self.assertEqual(
            legacy_request_links(make_legacy()),
            {"download_url": f"https://archive.example.com/legacy/{OID}.zip"},
        )

    @override_settings(LEGACY_DOWNLOAD_BASE_URL="https://archive.example.com/legacy/")
    def test_trailing_slash_does_not_double(self):
        links = legacy_request_links(make_legacy())
        self.assertEqual(
            links["download_url"], f"https://archive.example.com/legacy/{OID}.zip"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests.LegacyRequestLinksTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'legacy_request_links'`

- [ ] **Step 3: Add the setting**

In `backend/geoquery/settings.py`, directly below the existing `DOWNLOAD_BASE_URL` line (322):

```python
# Base URL for the copied archive of pre-2026 GeoQuery result zips, named
# <request_id>.zip. Empty until the archive is hosted; legacy requests then
# simply render no download link rather than a broken one.
LEGACY_DOWNLOAD_BASE_URL = os.environ.get("LEGACY_DOWNLOAD_BASE_URL", "")
```

- [ ] **Step 4: Add the function**

In `backend/analytics/services.py`, after `request_links`:

```python
def legacy_request_links(legacy_request) -> dict:
    """Download URL for an imported legacy request.

    Only a zip: the old system produced no equivalent of the documentation
    page or the visualization, and every imported row is already complete, so
    there is no "not ready yet" state. Empty when the base URL is unset, so
    this ships before the archive is hosted -- the same independent check
    ``request_links`` makes for each of its base URLs.
    """
    base = getattr(settings, "LEGACY_DOWNLOAD_BASE_URL", "").rstrip("/")
    if not base:
        return {}
    return {"download_url": f"{base}/{legacy_request.id}.zip"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests -v 2`
Expected: 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/geoquery/settings.py backend/analytics/services.py backend/analytics/tests/test_legacy_requests.py
git commit -m "Add legacy_request_links and LEGACY_DOWNLOAD_BASE_URL setting"
```

---

### Task 3: legacy_requests_for_user

**Goal:** Ownership resolution for legacy rows mirrors `requests_for_user` exactly — FK-claimed rows unioned with live matches on verified addresses.

**Files:**
- Modify: `backend/analytics/services.py` (after `requests_for_user`, ~line 558)
- Modify: `backend/analytics/tests/test_legacy_requests.py`

**Acceptance Criteria:**
- [ ] Rows claimed by FK are returned
- [ ] Rows matching a verified email are returned even with no FK set
- [ ] Rows matching an *unverified* email are NOT returned
- [ ] Another user's rows are never returned
- [ ] Results are ordered newest-submitted first

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `backend/analytics/tests/test_legacy_requests.py`:

```python
from allauth.account.models import EmailAddress

from analytics.services import legacy_requests_for_user


class LegacyRequestsForUserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", email="alice@example.com")
        EmailAddress.objects.create(
            user=self.user, email="alice@example.com", verified=True, primary=True
        )

    def test_returns_fk_claimed_rows(self):
        obj = make_legacy(id="a" * 24, contact="someone-else@example.com", user=self.user)
        self.assertEqual(list(legacy_requests_for_user(self.user)), [obj])

    def test_returns_verified_email_matches_without_fk(self):
        obj = make_legacy(id="b" * 24, contact="Alice@Example.com")
        self.assertEqual(list(legacy_requests_for_user(self.user)), [obj])

    def test_ignores_unverified_email_matches(self):
        EmailAddress.objects.create(
            user=self.user, email="alias@example.com", verified=False
        )
        make_legacy(id="c" * 24, contact="alias@example.com")
        self.assertEqual(list(legacy_requests_for_user(self.user)), [])

    def test_never_returns_another_users_rows(self):
        bob = User.objects.create_user(username="bob", email="bob@example.com")
        EmailAddress.objects.create(user=bob, email="bob@example.com", verified=True)
        make_legacy(id="d" * 24, contact="bob@example.com")
        self.assertEqual(list(legacy_requests_for_user(self.user)), [])

    def test_orders_newest_first(self):
        older = make_legacy(
            id="e" * 24,
            contact="alice@example.com",
            submit_time=datetime(2017, 1, 1, tzinfo=dt_timezone.utc),
        )
        newer = make_legacy(
            id="f" * 24,
            contact="alice@example.com",
            submit_time=datetime(2020, 1, 1, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(list(legacy_requests_for_user(self.user)), [newer, older])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests.LegacyRequestsForUserTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'legacy_requests_for_user'`

- [ ] **Step 3: Add the function**

In `backend/analytics/services.py`, immediately after `requests_for_user`. Note `Q` and `QuerySet` are already imported in this module.

```python
def legacy_requests_for_user(user) -> QuerySet["LegacyRequest"]:
    """Every legacy request belonging to ``user``, newest first.

    Deliberately mirrors ``requests_for_user`` rather than generalizing it:
    the two read side by side, so if ownership semantics ever drift apart the
    difference is visible in a diff.
    """
    from allauth.account.models import EmailAddress

    q = Q(user=user)
    emails = EmailAddress.objects.filter(user=user, verified=True).values_list(
        "email", flat=True
    )
    for email in emails:
        q |= Q(contact__iexact=email)

    return LegacyRequest.objects.filter(q).order_by("-submit_time")
```

`backend/analytics/services.py:39` already imports models at module level:

```python
from .models import ExtractTask, ProcessingOption, Request, RequestMap
```

Add `LegacyRequest` to it and drop the local `from analytics.models import LegacyRequest` line from the function body:

```python
from .models import ExtractTask, LegacyRequest, ProcessingOption, Request, RequestMap
```

The `EmailAddress` import stays local, matching how `requests_for_user` defers it.

- [ ] **Step 4: Run test to verify it passes**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_requests -v 2`
Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/analytics/services.py backend/analytics/tests/test_legacy_requests.py
git commit -m "Add legacy_requests_for_user ownership resolution"
```

---

### Task 4: Claim legacy requests on email verification

**Goal:** Verifying an email address attaches matching legacy rows to the account, with the same unclaimed-only semantics as `Request`.

**Files:**
- Modify: `backend/accounts/claims.py:10-27`
- Modify: `backend/accounts/tests.py`

**Acceptance Criteria:**
- [ ] `claim_requests_for_email` claims matching legacy rows case-insensitively
- [ ] Legacy rows already owned by another user are not re-claimed
- [ ] The returned count is the sum of current and legacy rows claimed
- [ ] Existing `Request` claim tests still pass unchanged

**Verify:** `sudo docker compose exec backend uv run python manage.py test accounts -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `backend/accounts/tests.py`:

```python
from datetime import datetime, timezone as dt_timezone

from analytics.models import LegacyRequest


def make_legacy_request(oid, contact, **overrides):
    fields = {
        "id": oid,
        "contact": contact,
        "custom_name": "Legacy request",
        "submit_time": datetime(2018, 5, 1, tzinfo=dt_timezone.utc),
        "complete_time": datetime(2018, 5, 1, 1, tzinfo=dt_timezone.utc),
        "boundary_title": "Kenya ADM1",
        "boundary_name": "ken_adm1_gadm28",
        "boundary_group": "ken_gadm28",
        "dataset_titles": ["Population"],
        "dataset_count": 1,
        "data": {},
    }
    fields.update(overrides)
    return LegacyRequest.objects.create(**fields)


class LegacyClaimTests(TestCase):
    def setUp(self):
        self.user = make_user("alice", "alice@example.com")

    def test_claims_legacy_requests_case_insensitively(self):
        legacy = make_legacy_request("a" * 24, "Alice@Example.com")
        other = make_legacy_request("b" * 24, "bob@example.com")

        claimed = claim_requests_for_email(self.user, "alice@example.com")

        self.assertEqual(claimed, 1)
        legacy.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(legacy.user, self.user)
        self.assertIsNone(other.user)

    def test_does_not_reclaim_owned_legacy_requests(self):
        bob = make_user("bob", "bob@example.com")
        make_legacy_request("c" * 24, "alice@example.com", user=bob)

        self.assertEqual(claim_requests_for_email(self.user, "alice@example.com"), 0)

    def test_count_sums_current_and_legacy(self):
        Request.objects.create(contact="alice@example.com", status=1)
        make_legacy_request("d" * 24, "alice@example.com")

        self.assertEqual(claim_requests_for_email(self.user, "alice@example.com"), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sudo docker compose exec backend uv run python manage.py test accounts.tests.LegacyClaimTests -v 2`
Expected: FAIL — the claim count is 0, because `claim_requests_for_email` only touches `Request`.

- [ ] **Step 3: Extend the claim helper**

Replace the body of `claim_requests_for_email` in `backend/accounts/claims.py`:

```python
def claim_requests_for_email(user, email: str) -> int:
    """Claim all unclaimed requests whose contact matches this verified email.

    Covers both current requests and the imported legacy ones: a user proving
    ownership of an address should get their whole history, not the half of it
    that postdates the rewrite.

    Only rows with no owner are taken, so claims are permanent: removing the
    email from the account later does not release them. Two accounts can never
    race for the same address because allauth enforces unique verified emails
    (ACCOUNT_UNIQUE_EMAIL).

    Returns the total number of requests claimed across both tables.
    """
    from analytics.models import LegacyRequest, Request

    email = (email or "").strip()
    if not email:
        return 0

    claimed = Request.objects.filter(
        contact__iexact=email, user__isnull=True
    ).update(user=user)
    claimed += LegacyRequest.objects.filter(
        contact__iexact=email, user__isnull=True
    ).update(user=user)
    return claimed
```

Also update the module docstring's first paragraph to say "requests" covers both tables:

```python
"""Attach historical requests to user accounts by verified email.

Requests predating the account system (and anonymous submissions) are keyed
only by the ``contact`` email string -- both in ``Request`` and in
``LegacyRequest``, the imported archive from the previous version of GeoQuery.
When a user proves ownership of an email address (allauth verification, or a
provider-verified email at social signup), every unclaimed request under that
address in either table becomes theirs.
"""
```

- [ ] **Step 4: Run the whole accounts suite**

Run: `sudo docker compose exec backend uv run python manage.py test accounts -v 2`
Expected: the three new tests pass and every pre-existing claim test still passes. The existing tests assert exact counts (e.g. `assertEqual(claimed, 2)`) but create no legacy rows, so the summed return value is unchanged for them.

- [ ] **Step 5: Commit**

```bash
git add backend/accounts/claims.py backend/accounts/tests.py
git commit -m "Claim legacy requests alongside current ones on email verification"
```

---

### Task 5: import_legacy_requests management command

**Goal:** A re-runnable command that upserts completed, in-window legacy requests from the Parquet export, skipping incomplete records and reporting what it did.

**Files:**
- Create: `backend/analytics/management/commands/import_legacy_requests.py`
- Create: `backend/analytics/tests/test_import_legacy_requests.py`

**Acceptance Criteria:**
- [ ] `--submitted-before` excludes rows submitted at or after the cutoff
- [ ] Rows with `status != 1` are excluded
- [ ] Rows with empty contact, empty boundary, or zero datasets are skipped, counted by reason
- [ ] Re-running the same import creates nothing and changes no field except `imported_at`
- [ ] A later cutoff adds only the newer rows
- [ ] `--dry-run` writes nothing
- [ ] Over-long CharField values are truncated rather than raising
- [ ] `dataset_titles` is release `custom_name` entries followed by raster `title` entries
- [ ] Verified-email owners are claimed after import

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_import_legacy_requests -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `backend/analytics/tests/test_import_legacy_requests.py`. The fixture writes a real Parquet file with the subset of columns the command reads, so the test exercises the actual reader rather than a mock.

```python
import tempfile
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from analytics.models import LegacyRequest

User = get_user_model()

# Only the columns the command reads, matching the types that
# request_migration/requests_to_parquet.py writes.
SCHEMA = pa.schema(
    [
        ("request_id", pa.string()),
        ("email", pa.string()),
        ("custom_name", pa.string()),
        ("status", pa.int64()),
        ("stage", pa.list_(pa.struct([("name", pa.string()), ("time", pa.int64())]))),
        (
            "boundary",
            pa.struct(
                [
                    ("title", pa.string()),
                    ("group", pa.string()),
                    ("name", pa.string()),
                    ("description", pa.string()),
                    ("path", pa.string()),
                ]
            ),
        ),
        (
            "release_data",
            pa.list_(
                pa.struct(
                    [
                        ("dataset", pa.string()),
                        ("custom_name", pa.string()),
                        ("hash", pa.string()),
                        ("filters", pa.map_(pa.string(), pa.list_(pa.string()))),
                    ]
                )
            ),
        ),
        (
            "raster_data",
            pa.list_(
                pa.struct(
                    [
                        ("name", pa.string()),
                        ("title", pa.string()),
                        ("base", pa.string()),
                        ("type", pa.string()),
                        ("custom_name", pa.string()),
                        ("temporal_type", pa.string()),
                        ("extract_types", pa.list_(pa.string())),
                        (
                            "files",
                            pa.list_(
                                pa.struct(
                                    [
                                        ("name", pa.string()),
                                        ("path", pa.string()),
                                        ("display", pa.string()),
                                        ("bytes", pa.int64()),
                                        ("start", pa.int64()),
                                        ("end", pa.int64()),
                                    ]
                                )
                            ),
                        ),
                    ]
                )
            ),
        ),
    ]
)

TS_2017 = int(datetime(2017, 3, 15, 18, 20, tzinfo=dt_timezone.utc).timestamp())
TS_2021 = int(datetime(2021, 6, 1, 9, 0, tzinfo=dt_timezone.utc).timestamp())


def record(
    oid,
    *,
    email="alice@example.com",
    name="Request 03-15-17 18:20",
    status=1,
    submitted=TS_2017,
    boundary_title="Tanzania ADM3 Boundary - GADM 2.8",
    boundary_name="tza_adm3_gadm28",
    releases=("World Bank Geocoded Aid Data v1.4.1",),
    rasters=("Population (GPW V4, UN Adjusted)",),
):
    return {
        "request_id": oid,
        "email": email,
        "custom_name": name,
        "status": status,
        "stage": [
            {"name": "submitted", "time": submitted},
            {"name": "completed", "time": submitted + 3600},
        ],
        "boundary": {
            "title": boundary_title,
            "group": "tza_gadm28",
            "name": boundary_name,
            "description": "GADM boundary",
            "path": "/data/TZA_adm3.geojson",
        },
        "release_data": [
            {"dataset": f"ds_{i}", "custom_name": t, "hash": "h", "filters": []}
            for i, t in enumerate(releases)
        ],
        "raster_data": [
            {
                "name": f"r_{i}",
                "title": t,
                "base": "/data",
                "type": "raster",
                "custom_name": t,
                "temporal_type": "year",
                "extract_types": ["mean"],
                "files": [],
            }
            for i, t in enumerate(rasters)
        ],
    }


def write_parquet(records, directory):
    path = Path(directory) / "requests.parquet"
    pq.write_table(pa.Table.from_pylist(records, schema=SCHEMA), path)
    return str(path)


class ImportLegacyRequestsTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_import(self, records, before="2026-01-01", **kwargs):
        path = write_parquet(records, self.tmp.name)
        call_command(
            "import_legacy_requests",
            parquet=path,
            submitted_before=before,
            verbosity=0,
            **kwargs,
        )

    def test_imports_a_completed_record(self):
        self.run_import([record("a" * 24)])

        obj = LegacyRequest.objects.get(pk="a" * 24)
        self.assertEqual(obj.contact, "alice@example.com")
        self.assertEqual(obj.boundary_name, "tza_adm3_gadm28")
        self.assertEqual(obj.dataset_count, 2)
        self.assertEqual(
            obj.dataset_titles,
            ["World Bank Geocoded Aid Data v1.4.1", "Population (GPW V4, UN Adjusted)"],
        )
        self.assertEqual(
            obj.submit_time,
            datetime(2017, 3, 15, 18, 20, tzinfo=dt_timezone.utc),
        )

    def test_excludes_rows_at_or_after_cutoff(self):
        self.run_import(
            [record("a" * 24, submitted=TS_2017), record("b" * 24, submitted=TS_2021)],
            before="2021-01-01",
        )
        self.assertEqual(
            list(LegacyRequest.objects.values_list("pk", flat=True)), ["a" * 24]
        )

    def test_excludes_non_completed(self):
        self.run_import([record("a" * 24, status=-2), record("b" * 24, status=1)])
        self.assertEqual(
            list(LegacyRequest.objects.values_list("pk", flat=True)), ["b" * 24]
        )

    def test_skips_empty_contact_boundary_and_datasets(self):
        self.run_import(
            [
                record("a" * 24, email=""),
                record("b" * 24, boundary_title="", boundary_name=""),
                record("c" * 24, releases=(), rasters=()),
                record("d" * 24),
            ]
        )
        self.assertEqual(
            list(LegacyRequest.objects.values_list("pk", flat=True)), ["d" * 24]
        )

    def test_rerun_is_idempotent(self):
        records = [record("a" * 24)]
        self.run_import(records)
        first = LegacyRequest.objects.get(pk="a" * 24)
        before = first.imported_at

        self.run_import(records)

        self.assertEqual(LegacyRequest.objects.count(), 1)
        again = LegacyRequest.objects.get(pk="a" * 24)
        self.assertEqual(again.custom_name, first.custom_name)
        self.assertEqual(again.dataset_titles, first.dataset_titles)
        # Strictly greater: imported_at is in UPDATE_FIELDS precisely so a
        # re-import records that it ran. assertGreaterEqual would pass even if
        # the field were never written.
        self.assertGreater(again.imported_at, before)

    def test_later_cutoff_adds_only_newer_rows(self):
        records = [record("a" * 24, submitted=TS_2017), record("b" * 24, submitted=TS_2021)]
        self.run_import(records, before="2021-01-01")
        self.run_import(records, before="2026-01-01")
        self.assertEqual(LegacyRequest.objects.count(), 2)

    def test_dry_run_writes_nothing(self):
        self.run_import([record("a" * 24)], dry_run=True)
        self.assertEqual(LegacyRequest.objects.count(), 0)

    def test_truncates_overlong_values(self):
        self.run_import([record("a" * 24, name="x" * 250)])
        self.assertEqual(len(LegacyRequest.objects.get(pk="a" * 24).custom_name), 100)

    def test_claims_verified_email_owners(self):
        user = User.objects.create_user(username="alice", email="alice@example.com")
        EmailAddress.objects.create(
            user=user, email="alice@example.com", verified=True, primary=True
        )

        self.run_import([record("a" * 24)])

        self.assertEqual(LegacyRequest.objects.get(pk="a" * 24).user, user)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_import_legacy_requests -v 2`
Expected: FAIL — `CommandError: Unknown command: 'import_legacy_requests'`

- [ ] **Step 3: Write the command**

Create `backend/analytics/management/commands/import_legacy_requests.py`:

```python
"""Import completed requests from the previous version of GeoQuery.

Reads the Parquet produced by ``request_migration/requests_to_parquet.py``
(itself a conversion of ``mongoexport --db=asdf --collection=det --jsonArray``)
and upserts them into ``analytics.LegacyRequest``.

The old system is still accepting submissions, so this is expected to run
twice: once now against a fixed ``--submitted-before`` date, and again when
that system is retired. Upserting on the preserved Mongo ObjectId makes the
second run safe -- it adds what is new and leaves everything else as it was.

Only completed requests are imported. Records missing a contact address, a
boundary, or any dataset are skipped and counted: they cannot be rendered
usefully, and the old system's own data has at least one of each.
"""

from collections import Counter
from datetime import datetime, timezone as dt_timezone

import pyarrow.parquet as pq
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.functions import Lower
from django.utils.dateparse import parse_date

from analytics.models import LegacyRequest

# Columns the command reads. Named explicitly so the Parquet can grow new
# ones without this command loading them.
COLUMNS = [
    "request_id",
    "email",
    "custom_name",
    "status",
    "stage",
    "boundary",
    "release_data",
    "raster_data",
]

COMPLETED = 1

# Fields written on conflict. `id` is the conflict target, so it is not
# listed. `imported_at` IS listed: with update_conflicts, Django writes only
# the fields named here, so leaving it out would keep the original timestamp
# and the column would mean "first imported" rather than "last run that
# touched this row", which is what the model documents.
UPDATE_FIELDS = [
    "contact",
    "custom_name",
    "submit_time",
    "complete_time",
    "boundary_title",
    "boundary_name",
    "boundary_group",
    "dataset_titles",
    "dataset_count",
    "data",
    "imported_at",
]

MAX_LENGTHS = {
    "contact": 100,
    "custom_name": 100,
    "boundary_title": 100,
    "boundary_name": 64,
    "boundary_group": 32,
}


def _plain(obj):
    """Make pyarrow output JSON-serializable.

    A Parquet map arrives from ``to_pylist`` as a list of (key, value) pairs;
    it round-trips far more usefully as an object.
    """
    if isinstance(obj, (list, tuple)):
        items = list(obj)
        if items and all(
            isinstance(i, tuple) and len(i) == 2 and isinstance(i[0], str)
            for i in items
        ):
            return {k: _plain(v) for k, v in items}
        return [_plain(i) for i in items]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    return obj


def _stage_times(stage):
    """``(submit_time, complete_time)`` as aware datetimes, or ``(None, None)``.

    Only these two stages are read. ``prepared`` and ``processed`` are
    deliberately ignored: in 9,716 of the exported completed rows they precede
    ``submitted``.
    """
    times = {s["name"]: s["time"] for s in stage or [] if s and s.get("name")}
    submitted, completed = times.get("submitted"), times.get("completed")
    if submitted is None or completed is None:
        return None, None
    return (
        datetime.fromtimestamp(submitted, tz=dt_timezone.utc),
        datetime.fromtimestamp(completed, tz=dt_timezone.utc),
    )


class Command(BaseCommand):
    help = (
        "Import completed requests from the previous version of GeoQuery out of "
        "a Parquet export. Upserts on the Mongo ObjectId, so it is safe to "
        "re-run; expected to run once now and again at cutover."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--parquet",
            required=True,
            help="Path to the Parquet file from requests_to_parquet.py.",
        )
        parser.add_argument(
            "--submitted-before",
            required=True,
            help=(
                "Import only requests submitted strictly before this ISO date "
                "(YYYY-MM-DD). Required so that no run depends on when it ran."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be imported without writing.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Rows per upsert batch (default 2000).",
        )

    def handle(self, *args, **options):
        cutoff_date = parse_date(options["submitted_before"])
        if cutoff_date is None:
            raise CommandError(
                f"--submitted-before must be an ISO date (YYYY-MM-DD), "
                f"got {options['submitted_before']!r}"
            )
        cutoff = datetime(
            cutoff_date.year, cutoff_date.month, cutoff_date.day,
            tzinfo=dt_timezone.utc,
        )

        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        verbosity = options["verbosity"]

        try:
            parquet = pq.ParquetFile(options["parquet"])
        except Exception as exc:
            raise CommandError(f"Could not open {options['parquet']}: {exc}") from exc

        skipped = Counter()
        truncated = Counter()
        contacts = set()
        batch = []
        written = 0

        for arrow_batch in parquet.iter_batches(
            batch_size=batch_size, columns=COLUMNS
        ):
            for rec in arrow_batch.to_pylist():
                obj = self._build(rec, cutoff, skipped, truncated)
                if obj is None:
                    continue
                batch.append(obj)
                contacts.add(obj.contact.lower())
                if len(batch) >= batch_size:
                    written += self._flush(batch, dry_run)
                    batch = []

        written += self._flush(batch, dry_run)

        claimed = 0
        if not dry_run and contacts:
            claimed = self._claim(contacts)

        if verbosity:
            self._report(written, skipped, truncated, claimed, dry_run)

    # ── internals ────────────────────────────────────────────────────────────

    def _build(self, rec, cutoff, skipped, truncated):
        """A LegacyRequest for this record, or None if it is filtered out."""
        if rec.get("status") != COMPLETED:
            skipped["not completed"] += 1
            return None

        submit_time, complete_time = _stage_times(rec.get("stage"))
        if submit_time is None:
            skipped["missing submit/complete time"] += 1
            return None
        if submit_time >= cutoff:
            skipped["at or after cutoff"] += 1
            return None

        contact = (rec.get("email") or "").strip()
        if not contact:
            skipped["empty contact"] += 1
            return None

        boundary = rec.get("boundary") or {}
        title = (boundary.get("title") or "").strip()
        name = (boundary.get("name") or "").strip()
        if not title or not name:
            skipped["empty boundary"] += 1
            return None

        releases = [r for r in (rec.get("release_data") or []) if r]
        rasters = [d for d in (rec.get("raster_data") or []) if d]
        # `count` counts entries; `titles` holds only those that carry a
        # display name. The two can legitimately differ -- the export has
        # entries with a null title -- so dataset_count is the number of
        # datasets requested, not the length of dataset_titles.
        titles = [r["custom_name"] for r in releases if r.get("custom_name")]
        titles += [d["title"] for d in rasters if d.get("title")]
        count = len(releases) + len(rasters)
        if count == 0:
            skipped["no datasets"] += 1
            return None

        values = {
            "contact": contact,
            "custom_name": (rec.get("custom_name") or "").strip(),
            "boundary_title": title,
            "boundary_name": name,
            "boundary_group": (boundary.get("group") or "").strip(),
        }
        for field, limit in MAX_LENGTHS.items():
            values[field] = self._trunc(values[field], limit, field, truncated)

        return LegacyRequest(
            id=rec["request_id"],
            submit_time=submit_time,
            complete_time=complete_time,
            dataset_titles=[self._trunc(t, 200, "dataset_titles", truncated)
                            for t in titles],
            dataset_count=count,
            data={
                "release_data": _plain(releases),
                "raster_data": _plain(rasters),
            },
            **values,
        )

    @staticmethod
    def _trunc(value, limit, field, truncated):
        """Cut `value` to `limit`, counting the cut.

        Array elements go through this too. A too-long element of
        `dataset_titles` is silently truncated by Postgres rather than
        raising the way an over-long scalar column does, so without this the
        import would report a clean run while quietly losing characters.
        """
        if value is not None and len(value) > limit:
            truncated[field] += 1
            return value[:limit]
        return value

    def _flush(self, batch, dry_run):
        if not batch or dry_run:
            return len(batch)
        with transaction.atomic():
            LegacyRequest.objects.bulk_create(
                batch,
                update_conflicts=True,
                unique_fields=["id"],
                update_fields=UPDATE_FIELDS,
            )
        return len(batch)

    def _claim(self, contacts):
        """Attach imported rows to accounts that already verified the address.

        Without this, a user who signed in before the import would see nothing
        until they re-verified. Reuses the tested claim helper rather than
        reimplementing its unclaimed-only semantics.
        """
        from allauth.account.models import EmailAddress

        from accounts.claims import claim_requests_for_email

        claimed = 0
        owners = (
            EmailAddress.objects.filter(verified=True)
            .annotate(lowered=Lower("email"))
            .filter(lowered__in=contacts)
            .values_list("user_id", "email")
        )
        from django.contrib.auth import get_user_model

        users = get_user_model().objects.in_bulk([uid for uid, _ in owners])
        for user_id, email in owners:
            user = users.get(user_id)
            if user is not None:
                claimed += claim_requests_for_email(user, email)
        return claimed

    def _report(self, written, skipped, truncated, claimed, dry_run):
        verb = "would import" if dry_run else "imported"
        self.stdout.write(self.style.SUCCESS(f"{verb} {written} legacy requests"))
        for reason, n in sorted(skipped.items()):
            self.stdout.write(f"  skipped {n}: {reason}")
        for field, n in sorted(truncated.items()):
            self.stdout.write(self.style.WARNING(f"  truncated {n}: {field}"))
        if not dry_run:
            self.stdout.write(f"  claimed by verified email: {claimed}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_import_legacy_requests -v 2`
Expected: 10 tests pass.

- [ ] **Step 5: Smoke-test against the real export**

The Parquet is gitignored and lives at `request_migration/requests.parquet`. Mount or copy it into the container, then:

```bash
sudo docker compose exec backend uv run python manage.py import_legacy_requests \
  --parquet /path/to/requests.parquet --submitted-before 2026-10-06 --dry-run
```

Expected: `would import 48666 legacy requests`, with `skipped 8: not completed` and `skipped 1: no datasets`. If the counts differ, reconcile before writing for real — those two numbers are the spec's and they are what the filters are designed around.

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/management/commands/import_legacy_requests.py backend/analytics/tests/test_import_legacy_requests.py
git commit -m "Add import_legacy_requests management command"
```

---

### Task 6: Legacy API endpoints

**Goal:** Three endpoints mirroring the current list, history and detail views, each marking its payload `is_legacy`.

**Files:**
- Modify: `backend/analytics/views.py` (append after `MyRequestsView`, ~line 360)
- Modify: `backend/analytics/urls.py`
- Create: `backend/analytics/tests/test_legacy_api.py`

**Acceptance Criteria:**
- [ ] `GET /api/analytics/legacy-requests/` returns the signed-in user's legacy requests and 403s anonymously
- [ ] `GET /api/analytics/legacy-history/<token>/` returns rows for the token's email, 404s on an unknown token and 410s on an expired one
- [ ] `GET /api/analytics/legacy-requests/<id>/` returns detail with `dataset_titles` and `boundary_title`, and 404s on an unknown id
- [ ] Every payload carries `is_legacy: true` and `status_label: "completed"`
- [ ] Detail includes `download_url` only when `LEGACY_DOWNLOAD_BASE_URL` is set
- [ ] One user never sees another's rows

**Verify:** `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_api -v 2` → OK

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `backend/analytics/tests/test_legacy_api.py`:

```python
from datetime import datetime, timedelta, timezone as dt_timezone

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from analytics.models import LegacyRequest, RequestToken

User = get_user_model()


def make_legacy(oid, contact="alice@example.com", **overrides):
    fields = {
        "id": oid,
        "contact": contact,
        "custom_name": "Request 03-15-17 18:20",
        "submit_time": datetime(2017, 3, 15, 18, 20, tzinfo=dt_timezone.utc),
        "complete_time": datetime(2017, 3, 15, 19, 20, tzinfo=dt_timezone.utc),
        "boundary_title": "Tanzania ADM3 Boundary - GADM 2.8",
        "boundary_name": "tza_adm3_gadm28",
        "boundary_group": "tza_gadm28",
        "dataset_titles": ["World Bank Geocoded Aid Data v1.4.1"],
        "dataset_count": 1,
        "data": {"release_data": [], "raster_data": []},
    }
    fields.update(overrides)
    return LegacyRequest.objects.create(**fields)


class LegacyMyRequestsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="alice", email="alice@example.com", password="pw"
        )
        EmailAddress.objects.create(
            user=self.user, email="alice@example.com", verified=True, primary=True
        )

    def test_requires_authentication(self):
        self.assertIn(
            self.client.get("/api/analytics/legacy-requests/").status_code, (401, 403)
        )

    def test_returns_own_rows_only(self):
        make_legacy("a" * 24)
        make_legacy("b" * 24, contact="bob@example.com")
        self.client.force_login(self.user)

        body = self.client.get("/api/analytics/legacy-requests/").json()

        self.assertEqual([r["id"] for r in body], ["a" * 24])
        self.assertTrue(body[0]["is_legacy"])
        self.assertEqual(body[0]["status_label"], "completed")
        self.assertEqual(body[0]["dataset_count"], 1)


class LegacyHistoryTests(TestCase):
    def test_returns_rows_for_token_email(self):
        make_legacy("a" * 24)
        make_legacy("b" * 24, contact="bob@example.com")
        _, raw = RequestToken.create_for_email(
            "alice@example.com", timezone.now() + timedelta(days=1)
        )

        body = self.client.get(f"/api/analytics/legacy-history/{raw}/").json()

        self.assertEqual([r["id"] for r in body], ["a" * 24])

    def test_unknown_token_is_404(self):
        self.assertEqual(
            self.client.get("/api/analytics/legacy-history/nope/").status_code, 404
        )

    def test_expired_token_is_410(self):
        _, raw = RequestToken.create_for_email(
            "alice@example.com", timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(
            self.client.get(f"/api/analytics/legacy-history/{raw}/").status_code, 410
        )


class LegacyDetailTests(TestCase):
    def test_returns_detail(self):
        make_legacy("a" * 24)

        body = self.client.get(f"/api/analytics/legacy-requests/{'a' * 24}/").json()

        self.assertEqual(body["name"], "Request 03-15-17 18:20")
        self.assertEqual(body["boundary_title"], "Tanzania ADM3 Boundary - GADM 2.8")
        self.assertEqual(
            body["dataset_titles"], ["World Bank Geocoded Aid Data v1.4.1"]
        )
        self.assertTrue(body["is_legacy"])

    def test_unknown_id_is_404(self):
        self.assertEqual(
            self.client.get(f"/api/analytics/legacy-requests/{'z' * 24}/").status_code,
            404,
        )

    @override_settings(LEGACY_DOWNLOAD_BASE_URL="")
    def test_no_download_url_when_unconfigured(self):
        make_legacy("a" * 24)
        body = self.client.get(f"/api/analytics/legacy-requests/{'a' * 24}/").json()
        self.assertNotIn("download_url", body)

    @override_settings(LEGACY_DOWNLOAD_BASE_URL="https://archive.example.com")
    def test_download_url_when_configured(self):
        make_legacy("a" * 24)
        body = self.client.get(f"/api/analytics/legacy-requests/{'a' * 24}/").json()
        self.assertEqual(
            body["download_url"], f"https://archive.example.com/{'a' * 24}.zip"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_api -v 2`
Expected: FAIL — 404s on every URL, because no routes exist yet.

- [ ] **Step 3: Add the views**

In `backend/analytics/views.py`, extend the existing imports:

```python
from .models import LegacyRequest, Request, RequestToken
from .services import (
    STATUS_LABELS as _STATUS_LABELS,
    NoExtractTasksError,
    create_request,
    legacy_request_links,
    legacy_requests_for_user,
    request_links,
    requests_for_user,
)
```

Then append after `MyRequestsView`:

```python
def _legacy_row(obj):
    """List representation of a legacy request.

    ``status_label`` is hardcoded because only completed requests are
    imported, and ``is_legacy`` is the flag the UI keys its treatment off.
    """
    return {
        "id": obj.id,
        "name": obj.custom_name,
        "submit_time": obj.submit_time,
        "complete_time": obj.complete_time,
        "dataset_count": obj.dataset_count,
        "status_label": "completed",
        "is_legacy": True,
    }


class LegacyMyRequestsView(APIView):
    """
    GET /api/analytics/legacy-requests/ — legacy history for the logged-in user
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            [_legacy_row(r) for r in legacy_requests_for_user(request.user)]
        )


class LegacyRequestHistoryView(APIView):
    """
    GET /api/analytics/legacy-history/<token>/ — legacy history for a valid token

    Shares RequestToken with the current-request history view, so a single
    magic link covers both halves of a user's history.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            token_obj = RequestToken.objects.get(token=RequestToken.hash_token(token))
        except RequestToken.DoesNotExist:
            return Response(
                {"error": "Invalid or expired link."}, status=status.HTTP_404_NOT_FOUND
            )

        if token_obj.is_expired:
            return Response(
                {"error": "This link has expired. Please request a new one."},
                status=status.HTTP_410_GONE,
            )

        qs = LegacyRequest.objects.filter(contact__iexact=token_obj.email).order_by(
            "-submit_time"
        )
        return Response([_legacy_row(r) for r in qs])


class LegacyRequestDetailView(APIView):
    """
    GET /api/analytics/legacy-requests/<id>/ — one legacy request by ObjectId

    AllowAny, matching RequestDetailView: holding the id is the capability.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            obj = LegacyRequest.objects.get(pk=pk)
        except LegacyRequest.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        data = _legacy_row(obj)
        data.update(
            {
                "boundary_title": obj.boundary_title,
                "boundary_name": obj.boundary_name,
                "boundary_group": obj.boundary_group,
                "dataset_titles": obj.dataset_titles,
            }
        )
        data.update(legacy_request_links(obj))
        return Response(data)
```

- [ ] **Step 4: Add the routes**

Replace `backend/analytics/urls.py` with:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("requests/", views.RequestView.as_view(), name="request-list-create"),
    path(
        "requests/<uuid:pk>/", views.RequestDetailView.as_view(), name="request-detail"
    ),
    path("request-token/", views.RequestTokenView.as_view(), name="request-token"),
    path("my-requests/", views.MyRequestsView.as_view(), name="my-requests"),
    path(
        "history/<str:token>/",
        views.RequestHistoryView.as_view(),
        name="request-history",
    ),
    # Legacy requests from the previous version of GeoQuery. Parallel to the
    # routes above rather than folded into them: the current payloads are bare
    # arrays shared with the MCP server, so adding a key would break it.
    path(
        "legacy-requests/",
        views.LegacyMyRequestsView.as_view(),
        name="legacy-my-requests",
    ),
    path(
        "legacy-requests/<str:pk>/",
        views.LegacyRequestDetailView.as_view(),
        name="legacy-request-detail",
    ),
    path(
        "legacy-history/<str:token>/",
        views.LegacyRequestHistoryView.as_view(),
        name="legacy-request-history",
    ),
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `sudo docker compose exec backend uv run python manage.py test analytics.tests.test_legacy_api -v 2`
Expected: 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/views.py backend/analytics/urls.py backend/analytics/tests/test_legacy_api.py
git commit -m "Add legacy request list, history and detail endpoints"
```

---

### Task 7: Frontend API types and fetchers

**Goal:** Typed client functions for the three legacy endpoints.

**Files:**
- Modify: `frontend/src/lib/api.ts` (types near `PastRequest`, line 255; fetchers near `fetchMyRequests`, line 403)

**Acceptance Criteria:**
- [ ] `LegacyPastRequest` and `LegacyRequestDetail` types exist and match the endpoint payloads
- [ ] `fetchMyLegacyRequests`, `fetchLegacyRequestsByToken`, `fetchLegacyRequestDetail` exist
- [ ] The token fetcher throws `'expired'` on 410, matching `fetchRequestsByToken`
- [ ] `bun run check` passes

**Verify:** `sudo docker compose exec frontend bun run check` → 0 errors

**Steps:**

- [ ] **Step 1: Add the types**

In `frontend/src/lib/api.ts`, after the `PastRequest` interface (line 261):

```typescript
/** A completed request imported from the previous version of GeoQuery. */
export interface LegacyPastRequest {
	id: string;
	name: string | null;
	submit_time: string;
	complete_time: string;
	dataset_count: number;
	status_label: 'completed';
	is_legacy: true;
}

export interface LegacyRequestDetail extends LegacyPastRequest {
	boundary_title: string;
	boundary_name: string;
	boundary_group: string;
	dataset_titles: string[];
	/** Absent until the archive base URL is configured. */
	download_url?: string;
}
```

- [ ] **Step 2: Add the fetchers**

After `fetchRequestsByToken` (line 420):

```typescript
export async function fetchMyLegacyRequests(): Promise<LegacyPastRequest[]> {
	const response = await apiFetch('/api/analytics/legacy-requests/');
	if (!response.ok) {
		throw new Error(`Failed to fetch legacy requests: ${response.status}`);
	}
	return response.json();
}

export async function fetchLegacyRequestsByToken(
	token: string
): Promise<LegacyPastRequest[]> {
	const response = await fetch(
		`/api/analytics/legacy-history/${encodeURIComponent(token)}/`
	);
	if (response.status === 410) {
		throw new Error('expired');
	}
	if (!response.ok) {
		throw new Error('invalid');
	}
	return response.json();
}

export async function fetchLegacyRequestDetail(
	id: string
): Promise<LegacyRequestDetail> {
	const response = await fetch(
		`/api/analytics/legacy-requests/${encodeURIComponent(id)}/`
	);
	if (!response.ok) {
		throw new Error(`Failed to fetch legacy request: ${response.status}`);
	}
	return response.json();
}
```

- [ ] **Step 3: Verify**

Run: `sudo docker compose exec frontend bun run check`
Expected: 0 errors, 0 warnings.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "Add frontend types and fetchers for legacy requests"
```

---

### Task 8: Archived requests section on the past-requests page

**Goal:** Legacy requests render in a collapsed, visually-distinct section below current requests, and are absent entirely when there are none.

**Files:**
- Modify: `frontend/src/routes/requests/[[token]]/+page.svelte`

**Acceptance Criteria:**
- [ ] Legacy requests load in parallel with current ones, for both the token and signed-in paths
- [ ] The section is collapsed by default and shows a count
- [ ] Rows are muted, carry an `Archive` badge, and link to `/requests/legacy/<id>`
- [ ] No section renders when the user has no legacy requests
- [ ] A legacy fetch failure does not break the current-requests list
- [ ] `bun run check` passes

**Verify:** `sudo docker compose exec frontend bun run check` → 0 errors, then load `http://localhost:5173/requests` signed in and confirm the section

**Steps:**

- [ ] **Step 1: Extend the script block**

In `frontend/src/routes/requests/[[token]]/+page.svelte`, update the imports:

```typescript
import { ArrowLeft, Search, Mail, BarChart2, LogIn, Archive, ChevronDown } from "@lucide/svelte";
import {
    requestHistoryLink,
    fetchRequestsByToken,
    fetchMyRequests,
    fetchLegacyRequestsByToken,
    fetchMyLegacyRequests,
    type PastRequest,
    type LegacyPastRequest
} from "$lib/api";
import * as Collapsible from "$lib/components/ui/collapsible";
```

Add state beside the existing `requests` declaration:

```typescript
let legacyRequests = $state<LegacyPastRequest[]>([]);
```

Replace `loadHistory` and `loadMine` so each loads both lists in parallel. A legacy
failure is swallowed: the archive is a bonus, and failing it must not cost the
user the list they came for.

```typescript
async function loadHistory(t: string) {
    loading = true;
    error = "";
    expired = false;
    try {
        const [current, legacy] = await Promise.all([
            fetchRequestsByToken(t),
            fetchLegacyRequestsByToken(t).catch(() => [])
        ]);
        requests = current;
        legacyRequests = legacy;
    } catch (e: any) {
        if (e.message === "expired") {
            expired = true;
        } else {
            error = "This link is invalid or has expired.";
        }
    } finally {
        loading = false;
    }
}

// Signed-in users see their linked requests directly — no magic link needed.
let showingMine = $state(false);
async function loadMine() {
    loading = true;
    error = "";
    try {
        const [current, legacy] = await Promise.all([
            fetchMyRequests(),
            fetchMyLegacyRequests().catch(() => [])
        ]);
        requests = current;
        legacyRequests = legacy;
        showingMine = true;
    } catch {
        error = "Failed to load your requests. Please try again.";
    } finally {
        loading = false;
    }
}
```

- [ ] **Step 2: Update the count line**

The existing paragraph reports `requests.length`. Replace that line so the archive is accounted for:

```svelte
<p class="mb-6 text-muted-foreground">
    {requests.length} request{requests.length === 1 ? "" : "s"} found{legacyRequests.length
        ? `, plus ${legacyRequests.length} archived`
        : ""}.
    {#if showingMine}
        Missing older requests? <a href="/account" class="underline">Verify another
        email address</a> to link them to your account.
    {/if}
</p>
```

- [ ] **Step 3: Render the archived section**

The relevant markup is lines 191-223: `{#if requests.length === 0}` at 191, the
`<div class="space-y-3">` list at 194, its closing `</div>` at 222, and the `{/if}`
at 223. Change the empty-state condition so a user with only legacy requests does
not see "No requests found", then insert the collapsible between line 222 and 223.

Replace:

```svelte
{#if requests.length === 0}
    <p class="text-center text-muted-foreground">No requests found for this account.</p>
{:else}
```

with:

```svelte
{#if requests.length === 0 && legacyRequests.length === 0}
    <p class="text-center text-muted-foreground">No requests found for this account.</p>
{:else}
```

Then, between the `</div>` closing the `space-y-3` list (line 222) and the `{/if}`
on line 223, insert:

```svelte
{#if legacyRequests.length > 0}
    <Collapsible.Root class="mt-6 border-t pt-4">
        <Collapsible.Trigger
            class="group flex w-full items-center justify-between rounded-md px-1 py-2 text-left hover:bg-muted/50"
        >
            <span class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <Archive class="h-4 w-4" />
                Archived requests (2016–2026)
                <span class="rounded-full bg-muted px-2 py-0.5 text-xs">
                    {legacyRequests.length}
                </span>
            </span>
            <ChevronDown
                class="h-4 w-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
            />
        </Collapsible.Trigger>
        <Collapsible.Content>
            <p class="px-1 py-2 text-xs text-muted-foreground">
                Requests from the previous version of GeoQuery. Results remain
                downloadable, but these cannot be re-run or visualized.
            </p>
            <div class="space-y-3">
                {#each legacyRequests as request}
                    <button
                        class="block w-full rounded-md border border-dashed bg-muted/20 p-4 text-left transition-colors hover:bg-muted/50"
                        onclick={() => goto(`/requests/legacy/${request.id}`)}
                    >
                        <div class="flex items-center justify-between gap-2">
                            <div class="font-medium text-muted-foreground">
                                {request.name || "Unnamed Request"}
                            </div>
                            <span
                                class="flex shrink-0 items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
                            >
                                <Archive class="h-3 w-3" />
                                archived
                            </span>
                        </div>
                        <div class="mt-1 text-sm text-muted-foreground">
                            {new Date(request.submit_time).toLocaleDateString()}
                            · {request.dataset_count} dataset{request.dataset_count === 1
                                ? ""
                                : "s"}
                        </div>
                    </button>
                {/each}
            </div>
        </Collapsible.Content>
    </Collapsible.Root>
{/if}
```

- [ ] **Step 4: Verify**

Run: `sudo docker compose exec frontend bun run check`
Expected: 0 errors.

Then with the stack up, sign in at `http://localhost:5173/requests` as a user whose
verified email matches imported legacy rows. Confirm: the section is present and
collapsed, the count is right, expanding reveals the rows, and clicking one
navigates to the legacy detail route.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/requests/\[\[token\]\]/+page.svelte
git commit -m "Add collapsed archived requests section to past requests page"
```

---

### Task 9: Legacy request detail page

**Goal:** A dedicated page showing a legacy request's summary, boundary, datasets and download link.

**Files:**
- Create: `frontend/src/routes/requests/legacy/[id]/+page.svelte`

**Acceptance Criteria:**
- [ ] Renders name, submitted and completed dates, boundary title, and dataset titles
- [ ] Shows a download button only when `download_url` is present
- [ ] Shows an explanatory note that the request cannot be re-run or visualized
- [ ] An unknown id renders a not-found message rather than a blank page
- [ ] `bun run check` passes

**Verify:** `sudo docker compose exec frontend bun run check` → 0 errors, then open `/requests/legacy/<id>`

**Steps:**

- [ ] **Step 1: Create the page**

Create `frontend/src/routes/requests/legacy/[id]/+page.svelte`:

```svelte
<script lang="ts">
    import { page } from "$app/state";
    import { goto } from "$app/navigation";
    import { Button } from "$lib/components/ui/button";
    import { ArrowLeft, Archive, Download } from "@lucide/svelte";
    import { fetchLegacyRequestDetail, type LegacyRequestDetail } from "$lib/api";

    const id = $derived(page.params.id ?? "");

    let request = $state<LegacyRequestDetail | null>(null);
    let loading = $state(true);
    let error = $state("");

    $effect(() => {
        if (!id) return;
        loading = true;
        error = "";
        fetchLegacyRequestDetail(id)
            .then((r) => {
                request = r;
            })
            .catch(() => {
                error = "This archived request could not be found.";
            })
            .finally(() => {
                loading = false;
            });
    });

    const fmt = (iso: string | null) =>
        iso ? new Date(iso).toLocaleDateString(undefined, {
            year: "numeric",
            month: "long",
            day: "numeric"
        }) : "—";
</script>

<div class="container mx-auto max-w-2xl px-4 py-8">
    <div class="mb-6">
        <Button variant="ghost" onclick={() => goto("/requests")}>
            <ArrowLeft class="mr-1 h-4 w-4" />
            Back to Requests
        </Button>
    </div>

    <div class="rounded-lg border bg-card p-6 shadow-sm">
        {#if loading}
            <p class="text-center text-muted-foreground">Loading…</p>
        {:else if error || !request}
            <h1 class="mb-2 text-2xl font-semibold">Not Found</h1>
            <p class="text-muted-foreground">{error}</p>
        {:else}
            <div class="mb-4 flex items-start justify-between gap-3">
                <h1 class="text-2xl font-semibold">
                    {request.name || "Unnamed Request"}
                </h1>
                <span
                    class="flex shrink-0 items-center gap-1 rounded-full bg-muted px-2 py-1 text-xs font-medium text-muted-foreground"
                >
                    <Archive class="h-3 w-3" />
                    archived
                </span>
            </div>

            <p class="mb-6 text-sm text-muted-foreground">
                This request was submitted to a previous version of GeoQuery. Its
                results remain available to download, but it cannot be re-run or
                visualized, and its datasets are not linked to the current catalog.
            </p>

            <dl class="space-y-3 text-sm">
                <div class="flex justify-between gap-4 border-b pb-2">
                    <dt class="text-muted-foreground">Submitted</dt>
                    <dd class="text-right">{fmt(request.submit_time)}</dd>
                </div>
                <div class="flex justify-between gap-4 border-b pb-2">
                    <dt class="text-muted-foreground">Completed</dt>
                    <dd class="text-right">{fmt(request.complete_time)}</dd>
                </div>
                <div class="flex justify-between gap-4 border-b pb-2">
                    <dt class="text-muted-foreground">Boundary</dt>
                    <dd class="text-right">{request.boundary_title}</dd>
                </div>
            </dl>

            <h2 class="mb-2 mt-6 text-sm font-medium">
                Datasets ({request.dataset_count})
            </h2>
            {#if request.dataset_titles.length > 0}
                <ul class="space-y-1 text-sm text-muted-foreground">
                    {#each request.dataset_titles as title}
                        <li class="rounded border bg-muted/20 px-3 py-1.5">{title}</li>
                    {/each}
                </ul>
            {:else}
                <p class="text-sm text-muted-foreground">
                    No dataset names were recorded for this request.
                </p>
            {/if}

            {#if request.download_url}
                <div class="mt-6">
                    <Button href={request.download_url}>
                        <Download class="mr-1 h-4 w-4" />
                        Download Results
                    </Button>
                </div>
            {/if}
        {/if}
    </div>
</div>
```

- [ ] **Step 2: Verify**

Run: `sudo docker compose exec frontend bun run check`
Expected: 0 errors.

Then open `http://localhost:5173/requests/legacy/<an imported id>` and confirm the
summary renders. Open `/requests/legacy/zzzzzzzzzzzzzzzzzzzzzzzz` and confirm the
not-found message rather than a blank card.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/requests/legacy/
git commit -m "Add legacy request detail page"
```

---

### Task 10: Report legacy request count in stats

**Goal:** The stats snapshot carries a legacy count, reported separately from current-system figures.

**Files:**
- Modify: `backend/stats/builder.py:11` (import) and `_collect`'s return dict (~line 129)
- Modify: `frontend/src/lib/api.ts` (`StatsData` interface, ~line 428)
- Modify: `frontend/src/routes/stats/+page.svelte` (~line 47)
- Modify: `backend/stats/tests.py`

**Acceptance Criteria:**
- [ ] The snapshot includes `legacy_request_count`
- [ ] The count is not folded into `total`, `status_counts` or either time series
- [ ] The stats page renders it as a distinct, labelled figure
- [ ] `bun run check` passes

**Verify:** `sudo docker compose exec backend uv run python manage.py test stats -v 2` → OK, and `sudo docker compose exec frontend bun run check` → 0 errors

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `backend/stats/tests.py`:

`stats/builder.py` reads through the `"replica"` alias (`_DB = "replica"`, line 27),
so this test MUST mix in `ReplicaReadsTestMixin` or the read sees an empty database
and the assertion fails for the wrong reason. Both it and `StatsBuilder` are already
imported at the top of `stats/tests.py`.

```python
class LegacyCountInSnapshotTests(ReplicaReadsTestMixin, TestCase):
    def test_snapshot_counts_legacy_requests_separately(self):
        from analytics.models import LegacyRequest

        LegacyRequest.objects.create(
            id="a" * 24,
            contact="alice@example.com",
            custom_name="Legacy",
            submit_time=datetime(2018, 1, 1, tzinfo=dt_timezone.utc),
            complete_time=datetime(2018, 1, 1, 1, tzinfo=dt_timezone.utc),
            boundary_title="Kenya ADM1",
            boundary_name="ken_adm1_gadm28",
            boundary_group="ken_gadm28",
            dataset_titles=["Population"],
            dataset_count=1,
            data={},
        )

        snapshot = StatsBuilder().collect()

        self.assertEqual(snapshot["legacy_request_count"], 1)
        # Legacy rows live in their own table and must not inflate the
        # current system's figures.
        self.assertEqual(snapshot["total"], 0)
```

`collect()` is the public entry point the existing tests use (`stats/tests.py:86`);
`_collect` is private and calling it directly bypasses the snapshot wrapper.

- [ ] **Step 2: Run test to verify it fails**

Run: `sudo docker compose exec backend uv run python manage.py test stats -v 2`
Expected: FAIL — `KeyError: 'legacy_request_count'`

The `datetime` import and `timezone as dt_timezone` alias may already exist at the top of `stats/tests.py` (it imports `datetime, timezone`); use the existing names rather than adding a duplicate import.

- [ ] **Step 3: Add the count to the snapshot**

In `backend/stats/builder.py`, extend the import on line 11:

```python
from analytics.models import ExtractTask, LegacyRequest, Request
```

In `_collect`, before the return, add:

```python
        # Requests imported from the previous version of GeoQuery. Reported as
        # its own figure rather than folded into the counts above: those
        # describe the current system's throughput, and a decade of another
        # system's history would distort every chart built from them.
        legacy_request_count = LegacyRequest.objects.using(_DB).count()
```

and add the key to the returned dict:

```python
            "legacy_request_count": legacy_request_count,
```

- [ ] **Step 4: Add the frontend field**

In `frontend/src/lib/api.ts`, add to the `StatsData` interface:

```typescript
	/** Requests imported from the previous version of GeoQuery. */
	legacy_request_count: number;
```

- [ ] **Step 5: Render it**

In `frontend/src/routes/stats/+page.svelte`, the status cards render from a `cards`
array into a grid that closes at line 127. Insert this immediately after that
closing `</div>`, as a separate line rather than a sixth card, so it reads as
context and not as a current-system status:

```svelte
{#if stats?.legacy_request_count}
    <p class="mt-2 text-xs text-muted-foreground">
        Plus {stats.legacy_request_count.toLocaleString()} archived requests from
        previous versions of GeoQuery, not included in the figures above.
    </p>
{/if}
```

For reference, the insertion point is the line after the `{/each}` + `</div>` that
close the `mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5` container. The file is
tab-indented; match it.

- [ ] **Step 6: Verify**

Run:
```bash
sudo docker compose exec backend uv run python manage.py test stats -v 2
sudo docker compose exec frontend bun run check
```
Expected: tests pass; 0 frontend errors.

- [ ] **Step 7: Commit**

```bash
git add backend/stats/builder.py backend/stats/tests.py frontend/src/lib/api.ts frontend/src/routes/stats/+page.svelte
git commit -m "Report legacy request count separately in stats"
```

---

## Final verification

After all tasks, run the full affected suites and the frontend check:

```bash
sudo docker compose exec backend uv run python manage.py test analytics accounts stats -v 2
sudo docker compose exec backend uv run python manage.py makemigrations --check --dry-run
sudo docker compose exec frontend bun run check
```

Expected: all tests pass, no pending migrations, no frontend errors.

Then the real import, against the fixed date:

```bash
sudo docker compose exec backend uv run python manage.py import_legacy_requests \
  --parquet /path/to/requests.parquet --submitted-before <fixed date> --dry-run
sudo docker compose exec backend uv run python manage.py import_legacy_requests \
  --parquet /path/to/requests.parquet --submitted-before <fixed date>
```

The `--dry-run` first: it reports the same counts the real run will write, and it is
the cheapest place to catch a wrong `--parquet` or a mistyped date.

## Deferred to the operator

- **`LEGACY_DOWNLOAD_BASE_URL` is left unset** by this plan. Until the zip archive is
  hosted, legacy detail pages render without a download button. Set the environment
  variable when the archive location is known — no code change needed.
- **The cutover re-run.** Re-run the import command with a later `--submitted-before`
  once the old system stops accepting submissions.
