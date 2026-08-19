# Public API (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a documented, versioned, read-only public API (`/api/public/v1/`) exposing datasets and boundaries, reusing existing GeoDjango query logic behind new public-facing serializers, with an auth/rate-limit seam ready for the upcoming accounts feature.

**Architecture:** A new Django app `public_api` mounted at `/api/public/v1/` in `geoquery/urls.py`. It imports querysets/services from the existing `datasets` and `features` apps but defines its own serializers, so the frontend's serializers can change without affecting the public contract. `drf-spectacular` generates an OpenAPI schema scoped only to `public_api`'s own URL patterns (passed explicitly via `patterns=`), so internal `/api/*` endpoints never appear in public docs.

**Tech Stack:** Django 5.2, Django REST Framework, `drf-spectacular` (new dependency) for OpenAPI schema/Swagger UI, GeoDjango/PostGIS (existing).

**User decisions (already made):**
- Architecture: split namespace inside DRF (`/api/public/v1/`), not a separate service — GeoDjango/PostGIS logic (spatial autocomplete, coverage queries) stays in one place.
- Design toward public consumers now (versioning + rate limiting + auth model), even though launch is later.
- Auth: "design the seam, not the system" — a pluggable `PublicApiKeyAuthentication` stub; real key issuance is owned by a separate, not-yet-built accounts feature.
- v1 scope: read-only datasets (list/detail/categories/coverage) and boundaries (autocomplete/presets) only. Extraction requests and visualization/tiles are deferred.
- STAC: noted as a future consumer of the same underlying querysets, no design/implementation changes now.

**Note on scope correction:** The approved spec (`docs/superpowers/specs/2026-08-19-public-api-design.md`) lists `GET /api/public/v1/datasets/coverage/`, but the internal endpoint it mirrors (`datasets/views.py::DatasetCoverageView`) is a `POST` (it takes a JSON body of feature IDs, avoiding URL length limits). This plan implements it as `POST` to match the real, working contract — the spec's `GET` was a documentation-level slip, not an intentional design choice.

---

## Task 1: Scaffold the `public_api` app, dependency, and scoped OpenAPI schema/docs routes

**Goal:** A new Django app is registered, mounted at `/api/public/v1/`, and serves a valid (initially empty) OpenAPI schema and Swagger UI — proving the scaffolding, dependency, and URL scoping work before any real endpoint exists.

**Files:**
- Modify: `backend/pyproject.toml` (add `drf-spectacular` dependency)
- Create: `backend/public_api/__init__.py`
- Create: `backend/public_api/apps.py`
- Create: `backend/public_api/urls.py`
- Create: `backend/public_api/tests/__init__.py`
- Create: `backend/public_api/tests/test_urls.py`
- Modify: `backend/geoquery/settings.py` (INSTALLED_APPS, REST_FRAMEWORK, new SPECTACULAR_SETTINGS block)
- Modify: `backend/geoquery/urls.py` (mount `public_api.urls`)

**Acceptance Criteria:**
- [ ] `GET /api/public/v1/schema/` returns HTTP 200 with a valid OpenAPI document (`openapi`, `info`, `paths` keys present, `paths` empty)
- [ ] `GET /api/public/v1/docs/` returns HTTP 200 (Swagger UI HTML)
- [ ] `djm check` passes with no errors

**Verify:** `djm test public_api` → `OK` (1 test), then `djm check` → `System check identified no issues`

**Steps:**

- [ ] **Step 1: Add the `drf-spectacular` dependency**

In `backend/pyproject.toml`, add the dependency in the `dependencies` list, right after `"django-cors-headers>=4.9.0",`:

```toml
    "django-cors-headers>=4.9.0",
    "drf-spectacular>=0.27.0",
```

Then from the repo root (`/home/userx/work/geoquery/geoquery-update`), lock and sync:

```bash
uv lock --upgrade-package drf-spectacular
uv sync --package geoquery-backend
```

- [ ] **Step 2: Rebuild the backend image so the container picks up the new dependency**

```bash
sudo docker compose -f /home/userx/work/geoquery/geoquery-update/docker-compose.yml build backend
sudo docker compose -f /home/userx/work/geoquery/geoquery-update/docker-compose.yml up -d backend
```

- [ ] **Step 3: Create the app package**

Create `backend/public_api/__init__.py` (empty file).

Create `backend/public_api/apps.py`:

```python
from django.apps import AppConfig


class PublicApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "public_api"
```

- [ ] **Step 4: Register the app and drf-spectacular in settings**

In `backend/geoquery/settings.py`, modify `INSTALLED_APPS` (currently ends `"visualize",\n]`):

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_celery_results",
    "geoquery",
    "features",
    "datasets",
    "analytics",
    "visualize",
    "public_api",
]
```

In the same file, modify the `REST_FRAMEWORK` dict to add `DEFAULT_SCHEMA_CLASS` and a new throttle rate for the public namespace:

```python
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "request_token": os.environ.get("THROTTLE_RATE_REQUEST_TOKEN", "10/hour"),
        "request_submit": os.environ.get("THROTTLE_RATE_REQUEST_SUBMIT", "60/hour"),
        "public_api_anon": os.environ.get("THROTTLE_RATE_PUBLIC_API_ANON", "100/hour"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "GeoQuery Public API",
    "DESCRIPTION": (
        "Read-only public API for GeoQuery datasets and boundaries. "
        "Currently open during beta; API key authentication will be "
        "required once account-based access launches."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
```

`DEFAULT_SCHEMA_CLASS` is global because it's the introspection engine drf-spectacular attaches to every DRF view (required for it to work at all) — it does not itself publish anything. What controls what's actually exposed is the `patterns=` argument passed to the schema view in `public_api/urls.py` below, which restricts traversal to only `public_api`'s own routes.

- [ ] **Step 5: Create `public_api/urls.py`**

```python
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

app_name = "public_api"

# Populated by later tasks as real endpoints are added. Passed to the
# schema view below so OpenAPI generation only ever traverses these
# routes, never the internal /api/* endpoints used by the frontend.
api_urlpatterns = []

urlpatterns = api_urlpatterns + [
    path(
        "schema/",
        SpectacularAPIView.as_view(patterns=api_urlpatterns),
        name="schema",
    ),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="public_api:schema"),
        name="docs",
    ),
]
```

- [ ] **Step 6: Mount the app in the project URLconf**

In `backend/geoquery/urls.py`, modify the `urlpatterns` list to add the public API include, right after the `visualize` line:

```python
urlpatterns = [
    path("stats/", stats_view, name="stats"),
    path("stats/workers/", workers_view, name="stats-workers"),
    path("admin/", admin.site.urls),
    path("api/config/", ConfigView.as_view(), name="config"),
    path("api/features/", include("features.urls")),
    path("api/datasets/", include("datasets.urls")),
    path("api/analytics/", include("analytics.urls")),
    path("api/visualize/", include("visualize.urls")),
    path("api/public/v1/", include("public_api.urls")),
]
```

- [ ] **Step 7: Write the bootstrap test**

Create `backend/public_api/tests/__init__.py` (empty file).

Create `backend/public_api/tests/test_urls.py`:

```python
from django.test import TestCase
from django.urls import reverse


class PublicApiScaffoldTests(TestCase):
    def test_schema_endpoint_returns_valid_empty_openapi_document(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("openapi", data)
        self.assertIn("info", data)
        self.assertEqual(data["paths"], {})

    def test_docs_endpoint_returns_swagger_ui(self):
        response = self.client.get(reverse("public_api:docs"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"swagger", response.content.lower())
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `djm test public_api`
Expected: `Ran 2 tests ... OK`

- [ ] **Step 9: Run the Django system check**

Run: `djm check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 10: Commit**

```bash
cd /home/userx/work/geoquery/geoquery-update
git add backend/pyproject.toml backend/uv.lock backend/public_api backend/geoquery/settings.py backend/geoquery/urls.py
git commit -m "Scaffold public_api app with scoped OpenAPI schema/docs routes"
```

---

## Task 2: Auth seam, throttle, and shared public error envelope

**Goal:** A reusable `PublicApiBaseMixin` gives every future public endpoint the auth seam, IP-based throttle, and standardized `{"error": {...}}` response format — all independently unit-tested without needing a real endpoint.

**Files:**
- Create: `backend/public_api/authentication.py`
- Create: `backend/public_api/throttling.py`
- Create: `backend/public_api/exceptions.py`
- Create: `backend/public_api/base.py`
- Create: `backend/public_api/tests/test_infrastructure.py`

**Acceptance Criteria:**
- [ ] `PublicApiKeyAuthentication.authenticate()` returns `None` for any `Authorization` header value (stubbed until the accounts feature lands)
- [ ] `PublicApiThrottle` throttles by IP under the `public_api_anon` scope when no consumer is resolved
- [ ] `public_api_exception_handler` converts DRF's default error shape into `{"error": {"code": ..., "message": ...}}`
- [ ] `PublicApiBaseMixin` wires all three into any DRF view that inherits it

**Verify:** `djm test public_api` → `OK` (9 tests total: 2 from Task 1 + 7 new)

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `backend/public_api/tests/test_infrastructure.py`:

```python
from django.test import RequestFactory, TestCase
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from public_api.authentication import PublicApiConsumer, PublicApiKeyAuthentication, resolve_api_key
from public_api.exceptions import public_api_exception_handler
from public_api.throttling import PublicApiThrottle


class PublicApiKeyAuthenticationTests(TestCase):
    def setUp(self):
        self.auth = PublicApiKeyAuthentication()
        self.factory = RequestFactory()

    def test_resolve_api_key_is_stubbed_to_always_return_none(self):
        self.assertIsNone(resolve_api_key("any-key-at-all"))

    def test_authenticate_returns_none_without_authorization_header(self):
        request = self.factory.get("/api/public/v1/datasets/")
        self.assertIsNone(self.auth.authenticate(request))

    def test_authenticate_returns_none_with_a_wellformed_key_header(self):
        request = self.factory.get(
            "/api/public/v1/datasets/", HTTP_AUTHORIZATION="Api-Key some-key-value"
        )
        self.assertIsNone(self.auth.authenticate(request))


class PublicApiThrottleTests(TestCase):
    def setUp(self):
        self.throttle = PublicApiThrottle()
        self.factory = APIRequestFactory()

    def test_cache_key_falls_back_to_ip_when_no_consumer_resolved(self):
        django_request = self.factory.get("/api/public/v1/datasets/", REMOTE_ADDR="203.0.113.5")
        request = Request(django_request)

        key = self.throttle.get_cache_key(request, view=APIView())

        self.assertIn("public_api_anon", key)
        self.assertEqual(self.throttle.scope, "public_api_anon")

    def test_cache_key_uses_consumer_tier_when_its_rate_is_configured(self):
        self.throttle.THROTTLE_RATES = {"public_api_anon": "100/hour", "premium": "500/hour"}
        django_request = self.factory.get("/api/public/v1/datasets/")
        request = Request(django_request)
        request._auth = PublicApiConsumer(id=42, rate_limit_tier="premium", is_active=True)

        key = self.throttle.get_cache_key(request, view=APIView())

        self.assertIn("consumer:42", key)
        self.assertEqual(self.throttle.scope, "premium")

    def test_cache_key_falls_back_to_anon_scope_when_tier_rate_is_unconfigured(self):
        django_request = self.factory.get("/api/public/v1/datasets/")
        request = Request(django_request)
        request._auth = PublicApiConsumer(id=42, rate_limit_tier="unconfigured-tier", is_active=True)

        key = self.throttle.get_cache_key(request, view=APIView())

        self.assertIn("consumer:42", key)
        self.assertEqual(self.throttle.scope, "public_api_anon")


class PublicApiExceptionHandlerTests(TestCase):
    def test_wraps_drf_error_in_public_envelope(self):
        response = public_api_exception_handler(NotFound("no such dataset"), context={})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.data,
            {"error": {"code": 404, "message": "no such dataset"}},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `djm test public_api`
Expected: `ModuleNotFoundError: No module named 'public_api.authentication'` (or similar import error)

- [ ] **Step 3: Implement the auth seam**

Create `backend/public_api/authentication.py`:

```python
from dataclasses import dataclass

from rest_framework.authentication import BaseAuthentication


@dataclass
class PublicApiConsumer:
    """Minimal shape a resolved public API credential must satisfy.

    The accounts feature (built separately) will supply the real lookup
    behind resolve_api_key(); this dataclass documents the interface it
    needs to produce, not a persisted model.
    """

    id: int
    rate_limit_tier: str
    is_active: bool


def resolve_api_key(key: str) -> PublicApiConsumer | None:
    """Resolve an API key string to a consumer.

    Stubbed until the accounts feature provides real key storage and
    issuance. Always returns None, so every request currently falls
    through to anonymous access. Swapping in a real lookup here is the
    only change needed to activate authenticated access.
    """
    return None


class PublicApiKeyAuthentication(BaseAuthentication):
    """Authenticates public_api requests via `Authorization: Api-Key <key>`.

    Never raises: an invalid or missing key simply yields no credentials,
    since every public_api view currently sets permission_classes to
    AllowAny (see PublicApiBaseMixin). Once real keys exist, an unresolved
    key still just means "anonymous" here — enforcing that a key is
    *required* is a permission-class concern, not this class's job.
    """

    keyword = "Api-Key"

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        prefix = f"{self.keyword} "
        if not auth_header.startswith(prefix):
            return None

        key = auth_header[len(prefix):].strip()
        if not key:
            return None

        consumer = resolve_api_key(key)
        if consumer is None or not consumer.is_active:
            return None

        return (consumer, key)
```

- [ ] **Step 4: Implement the throttle**

Create `backend/public_api/throttling.py`:

```python
from django.core.exceptions import ImproperlyConfigured
from rest_framework.throttling import SimpleRateThrottle


class PublicApiThrottle(SimpleRateThrottle):
    """Throttles /api/public/v1/ requests.

    Falls back to per-IP throttling under the `public_api_anon` scope
    today, since PublicApiKeyAuthentication never resolves a real
    consumer yet. Once it does, a resolved PublicApiConsumer's own
    rate_limit_tier becomes the throttle scope automatically — as long as
    that tier has a configured rate in DEFAULT_THROTTLE_RATES. An
    unrecognized tier degrades safely to the anonymous rate rather than
    raising, since this seam can't know what tier names a not-yet-built
    accounts feature will eventually define.
    """

    scope = "public_api_anon"

    def get_cache_key(self, request, view):
        consumer = getattr(request, "auth", None)
        if consumer is not None and getattr(consumer, "rate_limit_tier", None):
            self.scope = consumer.rate_limit_tier
            ident = f"consumer:{consumer.id}"
        else:
            self.scope = "public_api_anon"
            ident = self.get_ident(request)

        try:
            self.rate = self.get_rate()
        except ImproperlyConfigured:
            self.scope = "public_api_anon"
            self.rate = self.get_rate()

        self.num_requests, self.duration = self.parse_rate(self.rate)

        return self.cache_format % {"scope": self.scope, "ident": ident}
```

- [ ] **Step 5: Implement the error envelope**

Create `backend/public_api/exceptions.py`:

```python
from rest_framework.views import exception_handler as drf_exception_handler


def public_api_exception_handler(exc, context):
    """Wraps DRF's default error response in a stable {"error": {...}} envelope.

    Scoped to public_api views only (see PublicApiBaseMixin) so internal
    /api/* endpoints keep DRF's default error format unchanged.
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and set(detail.keys()) == {"detail"}:
        message = detail["detail"]
    else:
        message = detail

    response.data = {
        "error": {
            "code": response.status_code,
            "message": message,
        }
    }
    return response
```

- [ ] **Step 6: Implement the shared base mixin**

Create `backend/public_api/base.py`:

```python
from rest_framework.permissions import AllowAny

from .authentication import PublicApiKeyAuthentication
from .exceptions import public_api_exception_handler
from .throttling import PublicApiThrottle


class PublicApiBaseMixin:
    """Shared DRF configuration for every public_api view.

    Bundles the auth seam, IP/consumer-tier throttle, AllowAny permission
    (open during beta — see PublicApiKeyAuthentication), and the public
    error envelope, so each view only needs to declare this mixin plus
    its own serializer/queryset.
    """

    authentication_classes = [PublicApiKeyAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [PublicApiThrottle]

    def get_exception_handler(self):
        return public_api_exception_handler
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `djm test public_api`
Expected: `Ran 9 tests ... OK`

- [ ] **Step 8: Commit**

```bash
cd /home/userx/work/geoquery/geoquery-update
git add backend/public_api/authentication.py backend/public_api/throttling.py backend/public_api/exceptions.py backend/public_api/base.py backend/public_api/tests/test_infrastructure.py
git commit -m "Add public_api auth seam, throttle, and error envelope"
```

---

## Task 3: Public datasets endpoints

**Goal:** `/api/public/v1/datasets/`, `/datasets/{name}/`, `/datasets/categories/`, and `/datasets/coverage/` are live, documented, and backed by a stable, tested serializer contract.

**Files:**
- Create: `backend/public_api/serializers.py`
- Create: `backend/public_api/views.py`
- Modify: `backend/public_api/urls.py`
- Create: `backend/public_api/tests/test_datasets.py`

**Acceptance Criteria:**
- [ ] `GET /api/public/v1/datasets/` returns a flat JSON array of active+public datasets
- [ ] `GET /api/public/v1/datasets/{name}/` returns one dataset by name, 404 (via the public error envelope) if not found or not active/public
- [ ] `GET /api/public/v1/datasets/categories/` returns deduplicated `{tag, display}` objects
- [ ] `POST /api/public/v1/datasets/coverage/` returns datasets covering the given boundary IDs; returns a 400 envelope error for a malformed body
- [ ] `PublicDatasetSerializer`'s field set is locked down by a field-stability test
- [ ] All four routes appear in `GET /api/public/v1/schema/`'s `paths`

**Verify:** `djm test public_api` → `OK` (6 + new dataset tests, 12+ total)

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `backend/public_api/tests/test_datasets.py`:

```python
from django.test import TestCase
from django.urls import reverse

from analytics.models import Coverage
from datasets.models import Dataset
from features.models import Feature
from public_api.serializers import PublicDatasetSerializer

EXPECTED_DATASET_FIELDS = {
    "name",
    "title",
    "description",
    "type",
    "tags",
    "source_name",
    "source_url",
    "temporal_name",
    "temporal_type",
    "temporal_start",
    "temporal_end",
    "date_updated",
    "bbox",
}


def make_dataset(**overrides):
    defaults = dict(
        active=True,
        public=True,
        name="test-dataset",
        path="test-dataset",
        type="raster",
        title="Test Dataset",
    )
    defaults.update(overrides)
    return Dataset.objects.create(**defaults)


class PublicDatasetSerializerTests(TestCase):
    def test_field_stability(self):
        dataset = make_dataset()

        data = PublicDatasetSerializer(dataset).data

        self.assertEqual(set(data.keys()), EXPECTED_DATASET_FIELDS)

    def test_bbox_is_none_without_spatial_extent(self):
        dataset = make_dataset()

        data = PublicDatasetSerializer(dataset).data

        self.assertIsNone(data["bbox"])


class PublicDatasetListViewTests(TestCase):
    def test_returns_flat_list_of_active_public_datasets(self):
        make_dataset(name="visible-one", path="visible-one")
        make_dataset(name="hidden-inactive", path="hidden-inactive", active=False)
        make_dataset(name="hidden-private", path="hidden-private", public=False)

        response = self.client.get(reverse("public_api:dataset-list"))

        self.assertEqual(response.status_code, 200)
        names = {d["name"] for d in response.json()}
        self.assertEqual(names, {"visible-one"})


class PublicDatasetDetailViewTests(TestCase):
    def test_returns_dataset_by_name(self):
        make_dataset(name="lookup-me", path="lookup-me", title="Lookup Me")

        response = self.client.get(
            reverse("public_api:dataset-detail", kwargs={"name": "lookup-me"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "lookup-me")

    def test_missing_dataset_returns_public_envelope_404(self):
        response = self.client.get(
            reverse("public_api:dataset-detail", kwargs={"name": "does-not-exist"})
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
        self.assertIn("code", response.json()["error"])


class PublicDatasetCategoryViewTests(TestCase):
    def test_returns_deduplicated_tags(self):
        make_dataset(name="tagged-a", path="tagged-a", tags=["climate", "raster"])
        make_dataset(name="tagged-b", path="tagged-b", tags=["climate"])

        response = self.client.get(reverse("public_api:dataset-categories"))

        self.assertEqual(response.status_code, 200)
        tags = {c["tag"] for c in response.json()}
        self.assertEqual(tags, {"climate", "raster"})


class PublicDatasetCoverageViewTests(TestCase):
    def test_returns_datasets_covering_given_feature_ids(self):
        covered = make_dataset(name="covered", path="covered")
        uncovered = make_dataset(name="uncovered", path="uncovered")
        feature = Feature.objects.create(shape="POINT(0 0)")
        Coverage.objects.create(dataset=covered, geom_id=feature.id, status=1)

        response = self.client.post(
            reverse("public_api:dataset-coverage"),
            data={"featureIds": [feature.id]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        names = {d["name"] for d in response.json()}
        self.assertEqual(names, {"covered"})

    def test_malformed_body_returns_public_envelope_400(self):
        response = self.client.post(
            reverse("public_api:dataset-coverage"),
            data={"featureIds": "not-a-list"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class PublicApiSchemaCoversDatasetRoutesTests(TestCase):
    def test_dataset_paths_appear_in_schema(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")

        paths = response.json()["paths"]
        self.assertIn("/datasets/", paths)
        self.assertIn("/datasets/{name}/", paths)
        self.assertIn("/datasets/categories/", paths)
        self.assertIn("/datasets/coverage/", paths)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `djm test public_api`
Expected: `ModuleNotFoundError: No module named 'public_api.serializers'` (or similar)

- [ ] **Step 3: Implement the dataset serializer**

Create `backend/public_api/serializers.py`:

```python
from rest_framework import serializers

from datasets.models import Dataset


class PublicDatasetSerializer(serializers.ModelSerializer):
    bbox = serializers.SerializerMethodField()

    def get_bbox(self, obj):
        if obj.spatial_extent is None:
            return None
        xmin, ymin, xmax, ymax = obj.spatial_extent.extent
        return [xmin, ymin, xmax, ymax]

    class Meta:
        model = Dataset
        fields = [
            "name",
            "title",
            "description",
            "type",
            "tags",
            "source_name",
            "source_url",
            "temporal_name",
            "temporal_type",
            "temporal_start",
            "temporal_end",
            "date_updated",
            "bbox",
        ]


class PublicDatasetCategorySerializer(serializers.Serializer):
    tag = serializers.CharField()
    display = serializers.CharField()


class PublicDatasetCoverageRequestSerializer(serializers.Serializer):
    featureIds = serializers.ListField(child=serializers.IntegerField())
```

- [ ] **Step 4: Implement the dataset views**

Create `backend/public_api/views.py`:

```python
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Coverage
from datasets.models import Dataset

from .base import PublicApiBaseMixin
from .serializers import (
    PublicDatasetCategorySerializer,
    PublicDatasetCoverageRequestSerializer,
    PublicDatasetSerializer,
)


class PublicDatasetListView(PublicApiBaseMixin, generics.ListAPIView):
    """GET /api/public/v1/datasets/ — flat list of active, public datasets."""

    serializer_class = PublicDatasetSerializer

    def get_queryset(self):
        return Dataset.objects.filter(active=True, public=True).order_by("type", "-date_updated")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class PublicDatasetDetailView(PublicApiBaseMixin, generics.RetrieveAPIView):
    """GET /api/public/v1/datasets/{name}/ — a single dataset by name."""

    serializer_class = PublicDatasetSerializer
    lookup_field = "name"

    def get_queryset(self):
        return Dataset.objects.filter(active=True, public=True)


class PublicDatasetCategoryView(PublicApiBaseMixin, generics.ListAPIView):
    """GET /api/public/v1/datasets/categories/ — deduplicated dataset tags."""

    @extend_schema(responses=PublicDatasetCategorySerializer(many=True))
    def list(self, request, *args, **kwargs):
        tags = (
            Dataset.objects.filter(active=True, public=True)
            .exclude(tags__isnull=True)
            .exclude(tags=[])
            .values_list("tags", flat=True)
        )

        seen = set()
        categories = []
        for tag_list in tags:
            for tag in tag_list:
                if tag not in seen:
                    seen.add(tag)
                    categories.append({"tag": tag, "display": tag.replace("_", " ").title()})

        categories.sort(key=lambda c: c["display"])
        return Response(categories)


class PublicDatasetCoverageView(PublicApiBaseMixin, APIView):
    """POST /api/public/v1/datasets/coverage/

    Body: {"featureIds": [1, 2, 3, ...]}
    Returns datasets that have at least one Coverage record for any of the
    given boundary IDs. POST (not GET) to avoid URL length limits for large
    selections, matching the internal datasets/coverage/ endpoint.
    """

    @extend_schema(
        request=PublicDatasetCoverageRequestSerializer,
        responses=PublicDatasetSerializer(many=True),
    )
    def post(self, request):
        feature_ids = request.data.get("featureIds", [])
        if not isinstance(feature_ids, list) or not all(isinstance(i, int) for i in feature_ids):
            raise ValidationError({"featureIds": "must be a list of integers"})

        qs = Dataset.objects.filter(active=True, public=True)
        if feature_ids:
            covered_ids = (
                Coverage.objects.filter(geom_id__in=feature_ids)
                .values_list("dataset_id", flat=True)
                .distinct()
            )
            qs = qs.filter(id__in=covered_ids)

        qs = qs.order_by("type", "-date_updated")
        return Response(PublicDatasetSerializer(qs, many=True).data)
```

- [ ] **Step 5: Wire up the routes**

Modify `backend/public_api/urls.py` — add the views import and populate `api_urlpatterns`:

```python
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import views

app_name = "public_api"

api_urlpatterns = [
    path("datasets/", views.PublicDatasetListView.as_view(), name="dataset-list"),
    path("datasets/categories/", views.PublicDatasetCategoryView.as_view(), name="dataset-categories"),
    path("datasets/coverage/", views.PublicDatasetCoverageView.as_view(), name="dataset-coverage"),
    path("datasets/<str:name>/", views.PublicDatasetDetailView.as_view(), name="dataset-detail"),
]

urlpatterns = api_urlpatterns + [
    path(
        "schema/",
        SpectacularAPIView.as_view(patterns=api_urlpatterns),
        name="schema",
    ),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="public_api:schema"),
        name="docs",
    ),
]
```

Note the ordering: `datasets/categories/` and `datasets/coverage/` must be listed before `datasets/<str:name>/`, otherwise Django would match `"categories"` or `"coverage"` as a dataset `name` first.

- [ ] **Step 6: Run tests to verify they pass**

Run: `djm test public_api`
Expected: `OK`, all dataset tests passing

- [ ] **Step 7: Commit**

```bash
cd /home/userx/work/geoquery/geoquery-update
git add backend/public_api/serializers.py backend/public_api/views.py backend/public_api/urls.py backend/public_api/tests/test_datasets.py
git commit -m "Add public datasets endpoints (list, detail, categories, coverage)"
```

---

## Task 4: Public boundaries endpoints

**Goal:** `/api/public/v1/boundaries/autocomplete/` and `/boundaries/presets/` are live, documented, and reuse the existing `features` app's queryset and preset-caching logic rather than duplicating it.

**Files:**
- Modify: `backend/public_api/serializers.py`
- Modify: `backend/public_api/views.py`
- Modify: `backend/public_api/urls.py`
- Create: `backend/public_api/tests/test_boundaries.py`

**Acceptance Criteria:**
- [ ] `GET /api/public/v1/boundaries/autocomplete/?q=...&limit=...` returns matching active+public feature collections
- [ ] A non-integer `limit` returns a 400 via the public error envelope
- [ ] `GET /api/public/v1/boundaries/presets/` returns the same preset list as the internal endpoint, reusing `features.views.BoundaryPresetsView._load_presets`
- [ ] `PublicBoundarySerializer`'s field set is locked down by a field-stability test
- [ ] Both routes appear in `GET /api/public/v1/schema/`'s `paths`

**Verify:** `djm test public_api` → `OK`, all tests passing

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `backend/public_api/tests/test_boundaries.py`:

```python
from django.test import TestCase
from django.urls import reverse

from features.models import FeatureCollection
from public_api.serializers import PublicBoundarySerializer

EXPECTED_BOUNDARY_FIELDS = {
    "name",
    "title",
    "short_name",
    "description",
    "bbox",
    "group_name",
    "group_title",
    "group_level",
    "source_name",
    "tags",
}


def make_boundary(**overrides):
    defaults = dict(
        active=True,
        public=True,
        name="test-boundary",
        path="test-boundary",
        title="Test Boundary",
    )
    defaults.update(overrides)
    return FeatureCollection.objects.create(**defaults)


class PublicBoundarySerializerTests(TestCase):
    def test_field_stability(self):
        boundary = make_boundary()

        data = PublicBoundarySerializer(boundary).data

        self.assertEqual(set(data.keys()), EXPECTED_BOUNDARY_FIELDS)


class PublicBoundaryAutocompleteViewTests(TestCase):
    def test_filters_to_active_public_boundaries_matching_query(self):
        make_boundary(name="wm-districts", path="wm-districts", title="William & Mary Districts")
        make_boundary(name="hidden-inactive", path="hidden-inactive", active=False)

        response = self.client.get(reverse("public_api:boundary-autocomplete"), {"q": "William"})

        self.assertEqual(response.status_code, 200)
        names = {b["name"] for b in response.json()}
        self.assertEqual(names, {"wm-districts"})

    def test_invalid_limit_returns_public_envelope_400(self):
        response = self.client.get(reverse("public_api:boundary-autocomplete"), {"limit": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class PublicBoundaryPresetsViewTests(TestCase):
    def test_returns_presets_from_yaml_via_shared_loader(self):
        response = self.client.get(reverse("public_api:boundary-presets"))

        self.assertEqual(response.status_code, 200)
        presets = response.json()
        self.assertIsInstance(presets, list)
        if presets:
            self.assertIn("name", presets[0])
            self.assertIn("sort_order", presets[0])


class PublicApiSchemaCoversBoundaryRoutesTests(TestCase):
    def test_boundary_paths_appear_in_schema(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")

        paths = response.json()["paths"]
        self.assertIn("/boundaries/autocomplete/", paths)
        self.assertIn("/boundaries/presets/", paths)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `djm test public_api`
Expected: `AttributeError` or `ImportError` referencing `PublicBoundarySerializer` (doesn't exist yet)

- [ ] **Step 3: Add the boundary serializers**

Modify `backend/public_api/serializers.py` — add these classes at the end of the file, and add the new import at the top:

```python
from features.models import FeatureCollection
```

```python
class PublicBoundarySerializer(serializers.ModelSerializer):
    bbox = serializers.SerializerMethodField()

    def get_bbox(self, obj):
        if obj.spatial_extent is None:
            return None
        xmin, ymin, xmax, ymax = obj.spatial_extent.extent
        return [xmin, ymin, xmax, ymax]

    class Meta:
        model = FeatureCollection
        fields = [
            "name",
            "title",
            "short_name",
            "description",
            "bbox",
            "group_name",
            "group_title",
            "group_level",
            "source_name",
            "tags",
        ]


class PublicBoundaryPresetSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True, required=False)
    source_name = serializers.CharField(allow_null=True, required=False)
    group_class = serializers.CharField(allow_null=True, required=False)
    group_level = serializers.IntegerField(allow_null=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    sort_order = serializers.IntegerField(required=False)
```

- [ ] **Step 4: Add the boundary views**

Modify `backend/public_api/views.py` — add these imports at the top:

```python
from django.db.models import Q

from features.models import FeatureCollection
from features.views import BoundaryPresetsView as _InternalBoundaryPresetsView
```

Add `PublicBoundarySerializer` and `PublicBoundaryPresetSerializer` to the existing `.serializers` import line.

Append these view classes at the end of the file:

```python
class PublicBoundaryAutocompleteView(PublicApiBaseMixin, generics.ListAPIView):
    """GET /api/public/v1/boundaries/autocomplete/?q=&limit= — search active, public boundaries."""

    serializer_class = PublicBoundarySerializer

    def get_queryset(self):
        query = self.request.query_params.get("q", "").strip()
        try:
            limit = int(self.request.query_params.get("limit", 10))
        except (ValueError, TypeError):
            raise ValidationError({"limit": "must be an integer"})

        queryset = FeatureCollection.objects.filter(active=True, public=True)
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(title__icontains=query)
                | Q(description__icontains=query)
            )
        queryset = queryset.order_by("name")
        if limit > 0:
            queryset = queryset[:limit]
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class PublicBoundaryPresetsView(PublicApiBaseMixin, APIView):
    """GET /api/public/v1/boundaries/presets/

    Reuses features.views.BoundaryPresetsView's cached YAML loader rather
    than duplicating the preset-loading/caching logic.
    """

    @extend_schema(responses=PublicBoundaryPresetSerializer(many=True))
    def get(self, request):
        presets = _InternalBoundaryPresetsView._load_presets()
        serializer = PublicBoundaryPresetSerializer(presets, many=True)
        return Response(serializer.data)
```

- [ ] **Step 5: Wire up the routes**

Modify `backend/public_api/urls.py` — add the two new routes to `api_urlpatterns`:

```python
api_urlpatterns = [
    path("datasets/", views.PublicDatasetListView.as_view(), name="dataset-list"),
    path("datasets/categories/", views.PublicDatasetCategoryView.as_view(), name="dataset-categories"),
    path("datasets/coverage/", views.PublicDatasetCoverageView.as_view(), name="dataset-coverage"),
    path("datasets/<str:name>/", views.PublicDatasetDetailView.as_view(), name="dataset-detail"),
    path("boundaries/autocomplete/", views.PublicBoundaryAutocompleteView.as_view(), name="boundary-autocomplete"),
    path("boundaries/presets/", views.PublicBoundaryPresetsView.as_view(), name="boundary-presets"),
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `djm test public_api`
Expected: `OK`, all boundary tests passing

- [ ] **Step 7: Commit**

```bash
cd /home/userx/work/geoquery/geoquery-update
git add backend/public_api/serializers.py backend/public_api/views.py backend/public_api/urls.py backend/public_api/tests/test_boundaries.py
git commit -m "Add public boundaries endpoints (autocomplete, presets)"
```

---

## Task 5: Full schema validity check

**Goal:** With every v1 endpoint in place, confirm the complete generated OpenAPI document is well-formed and covers exactly the six intended public routes — the final integration check tying Tasks 1-4 together.

**Files:**
- Create: `backend/public_api/tests/test_schema.py`

**Acceptance Criteria:**
- [ ] The full schema document has non-empty `openapi`, `info.title`, `info.version`
- [ ] `paths` contains exactly the six v1 routes and no others (proving `patterns=api_urlpatterns` scoping excludes internal `/api/*` endpoints and the schema/docs routes themselves)
- [ ] Every path has at least one HTTP method with a `responses` entry (proving `extend_schema` annotations on the plain-`APIView` endpoints took effect)

**Verify:** `djm test public_api` → `OK`, full suite green

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `backend/public_api/tests/test_schema.py`:

```python
from django.test import TestCase
from django.urls import reverse

EXPECTED_PATHS = {
    "/datasets/",
    "/datasets/categories/",
    "/datasets/coverage/",
    "/datasets/{name}/",
    "/boundaries/autocomplete/",
    "/boundaries/presets/",
}


class PublicApiFullSchemaTests(TestCase):
    def setUp(self):
        response = self.client.get(reverse("public_api:schema"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.schema = response.json()

    def test_schema_document_metadata_is_present(self):
        self.assertEqual(self.schema["openapi"][0], "3")
        self.assertEqual(self.schema["info"]["title"], "GeoQuery Public API")
        self.assertTrue(self.schema["info"]["version"])

    def test_schema_covers_exactly_the_v1_public_routes(self):
        self.assertEqual(set(self.schema["paths"].keys()), EXPECTED_PATHS)

    def test_every_path_documents_at_least_one_response(self):
        for path, operations in self.schema["paths"].items():
            for method, operation in operations.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                self.assertTrue(
                    operation.get("responses"),
                    f"{method.upper()} {path} has no documented responses",
                )
```

- [ ] **Step 2: Run the test to verify it fails or passes as expected**

Run: `djm test public_api`
Expected: if Tasks 1-4 were implemented correctly, this should already `PASS` — it's an integration check, not new production code. If `test_schema_covers_exactly_the_v1_public_routes` fails, compare the diff between `EXPECTED_PATHS` and the actual `paths` keys to find a routing mismatch from an earlier task.

- [ ] **Step 3: Run the full public_api suite**

Run: `djm test public_api`
Expected: `OK`, all tests across all four test modules passing

- [ ] **Step 4: Commit**

```bash
cd /home/userx/work/geoquery/geoquery-update
git add backend/public_api/tests/test_schema.py
git commit -m "Add full public API schema validity test"
```

---

## Self-Review Notes

- **Spec coverage:** Architecture (Task 1), versioning (URL-path `v1/`, Task 1), auth seam (Task 2), rate limiting (Task 2), datasets endpoint scope (Task 3), boundaries endpoint scope (Task 4), error envelope (Task 2, exercised end-to-end in Tasks 3-4), testing conventions incl. field-stability + schema-validity (Tasks 3-5) — all spec sections have a corresponding task.
- **Scope correction:** `datasets/coverage/` implemented as `POST` (matching the real internal endpoint), not `GET` as literally written in the spec — see the note under Architecture above.
- **Out of scope, unchanged:** `ApiKey` model/issuance, extraction request endpoints, visualization/tile endpoints, STAC — none of these have tasks here, matching the spec's "Out of scope" section.
