"""Request submission, decoupled from HTTP.

``RequestView.post`` used to be the only way to create a Request, so the rules
that decide what an extraction actually covers -- which datasets and boundaries
the caller may reach, which ExtractTasks get reused rather than recreated, which
skipped inputs produce a warning -- lived inside a DRF view and could only be
reached with a request object. The MCP server needs exactly those rules, from a
process with no HTTP layer at all, so they live here and the view calls in.

This is a move, not a rewrite: the standard (non-custom-boundary) path behaves
byte for byte as it did, down to warning wording and order, because both the
web API's response shape and its test suite pin it.

The custom-boundary path deliberately stayed in the view -- it does not create
tasks at all, it hands a GeoJSON upload to a Celery ingest task, and the MCP
server does not offer uploads.

``_build_tasks`` uses one bulk SELECT per resolved dataset to avoid N+1 queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.db.models.expressions import RawSQL

from catalog.access import (
    visible_datasets,
    visible_feature_collections,
    visible_processing_options_for_dataset,
)
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap

from .models import ExtractTask, ProcessingOption, Request, RequestMap

# Request.status as a word. Also imported by analytics.views, which exposed
# this mapping long before the service existed.
STATUS_LABELS = {
    -2: "error",
    -1: "queued",
    0: "processing",
    1: "completed",
    2: "preparing",
    3: "ingesting",
    4: "materializing",
}


class NoExtractTasksError(Exception):
    """Nothing in the submission resolved to a single extract task.

    Carries the accumulated warnings, which are the only explanation of *why*
    -- a dataset name that does not exist, or one the caller cannot see, or a
    selection with no features in it all land here.
    """

    def __init__(self, warnings: list[str]):
        super().__init__("No extract tasks found for the submitted datasets.")
        self.warnings = warnings


@dataclass(frozen=True)
class ResolvedDataset:
    """One submitted dataset spec, resolved against what the caller may see."""

    spec: dict
    dataset: Dataset
    pos: list[ProcessingOption]
    resources: list[DatasetResource]
    fms: list[FeatMap]
    task_kwargs: dict | None

    @property
    def task_count(self) -> int:
        # Every (feature, resource, option) triple is distinct, so the product
        # is the exact task count, not an upper bound.
        return len(self.fms) * len(self.resources) * len(self.pos)


@dataclass(frozen=True)
class RequestPlan:
    """What a submission would do, worked out without writing anything.

    ``preview_request`` hands this straight to the user; ``create_request``
    builds one and then acts on it. Resolving and creating are the same code
    path either way, so a preview cannot drift from the submission it previews.
    """

    resolved: list[ResolvedDataset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def task_count(self) -> int:
        return sum(r.task_count for r in self.resolved)


@dataclass(frozen=True)
class CreatedRequest:
    request: Request
    task_count: int
    warnings: list[str]

    def as_response_dict(self) -> dict:
        """The exact JSON body ``POST /api/analytics/requests/`` has always returned.

        ``warnings`` is present only when non-empty -- clients distinguish
        "submitted cleanly" from "submitted with skips" by the key's presence.
        """
        data = {
            "id": str(self.request.id),
            "name": self.request.custom_name,
            "status": self.request.status,
            "status_label": STATUS_LABELS.get(self.request.status, "unknown"),
            "submit_time": self.request.submit_time,
            "task_count": self.task_count,
        }
        if self.warnings:
            data["warnings"] = self.warnings
        return data


def resolve_request_plan(user, feature_ids: list[int], datasets: list[dict]) -> RequestPlan:
    """Resolve submitted dataset specs against the caller's visibility.

    Creates nothing. Every dataset that cannot be fully resolved is skipped
    with a warning rather than failing the whole submission, because a
    selection spanning many datasets is normal and one stale name should not
    discard the rest.
    """
    resolved: list[ResolvedDataset] = []
    warnings: list[str] = []
    visible_fcs = visible_feature_collections(user)

    for ds in datasets:
        dataset_name = (ds.get("datasetName") or "").strip()
        extract_types = ds.get("extractTypes") or []
        resources = ds.get("resources") or []
        task_kwargs = ds.get("kwargs") or None

        if not dataset_name:
            warnings.append(f"Skipped dataset missing datasetName: {ds}")
            continue

        # Resolve the dataset through the visibility rule for BOTH branches.
        # This previously only happened on the kwargs path, and only checked
        # `active`, so an active-but-not-public dataset was submittable by
        # name even though it never appeared in /api/datasets/.
        try:
            dataset_obj = visible_datasets(user).get(name=dataset_name)
        except Dataset.DoesNotExist:
            warnings.append(f"Dataset '{dataset_name}' not found or not available.")
            continue

        po_qs = visible_processing_options_for_dataset(user, dataset_obj)
        if extract_types:
            po_qs = po_qs.filter(short_name__in=extract_types)

        resource_qs = DatasetResource.objects.filter(dataset=dataset_obj)
        if resources:
            resource_qs = resource_qs.filter(name__in=resources)

        pos = list(po_qs)
        resource_list = list(resource_qs)
        # Feature ids reachable only through a collection the caller
        # cannot see must not produce tasks.
        fms = list(FeatMap.objects.filter(geom_id__in=feature_ids, fc__in=visible_fcs))

        if not pos or not resource_list or not fms:
            warnings.append(
                f"No processing options, resources, or features found for dataset '{dataset_name}'."
            )
            continue

        resolved.append(
            ResolvedDataset(
                spec=ds,
                dataset=dataset_obj,
                pos=pos,
                resources=resource_list,
                fms=fms,
                task_kwargs=task_kwargs,
            )
        )

    return RequestPlan(resolved=resolved, warnings=warnings)


def _get_or_create_task(resolved: ResolvedDataset, fm: FeatMap, resource, po):
    """Reuse the matching ExtractTask if there is one, else create it.

    The functional unique indexes (migration 0024) are:
      (dataset_id, fm_id, po_id, resource_ids_hash) WHERE kwargs IS NULL
      (dataset_id, fm_id, po_id, resource_ids_hash, MD5(kwargs::text))
          WHERE kwargs IS NOT NULL
    resource_ids_hash is a stored generated column computed via the
    extract_tasks_resource_ids_hash(integer[]) SQL function (see migration
    0024 -- plain hashtext(resource_ids::text) can't back a GENERATED column
    since the generic array cast is only STABLE, not IMMUTABLE). Filtering on
    it directly here, via the same function, lets Postgres use an exact index
    hit on all four columns instead of a 3-column prefix (dataset_id, fm_id,
    po_id) followed by a heap recheck of resource_ids. Still also filter on
    resource_ids itself (not just the hash) so a hash collision -- vanishingly
    unlikely, but hashtext() is a 32-bit hash -- can never return the wrong
    row; the hash is purely an index-selectivity optimization, resource_ids
    remains the actual correctness check.

    Django JSONField maps None to JSON null for equality queries, but rows with
    no kwargs (e.g. from build_extract_tasks) have SQL NULL. Use isnull lookup
    for the None case so the GET matches SQL NULL rows.
    """
    task_kwargs = resolved.task_kwargs
    if task_kwargs is None:
        kwargs_lookup = {"kwargs__isnull": True}
    else:
        kwargs_lookup = {"kwargs": task_kwargs}

    resource_ids = [resource.id]
    resource_ids_hash = RawSQL("extract_tasks_resource_ids_hash(%s)", [resource_ids])
    lookup = {
        "dataset_id": resolved.dataset.id,
        "resource_ids": resource_ids,
        "resource_ids_hash": resource_ids_hash,
        "fm": fm,
        "po": po,
        **kwargs_lookup,
    }
    try:
        return ExtractTask.objects.get(**lookup)
    except ExtractTask.DoesNotExist:
        try:
            # resource_ids_hash is NOT set here -- it's a generated column
            # (migration 0024), Postgres computes it automatically from
            # resource_ids on INSERT; explicitly setting a generated column's
            # value raises an error.
            return ExtractTask.objects.create(
                dataset_id=resolved.dataset.id,
                resource_ids=resource_ids,
                fm=fm,
                po=po,
                kwargs=task_kwargs,
            )
        except IntegrityError:
            return ExtractTask.objects.get(**lookup)


def _build_tasks(plan: RequestPlan) -> tuple[dict[int, int], list[dict]]:
    """Materialize a plan's ExtractTasks.

    Returns ``({task_id: dataset_id}, valid_datasets)``. A dict rather than a
    flat set[int] because RequestMap carries dataset_id per row (the
    partition-key-adjacent column): it dedupes on task_id the same way the old
    set did, while still recording which dataset each task belongs to.

    Fetches existing tasks in one SELECT per resolved dataset rather than one
    per (fm, resource, po) triple. _get_or_create_task is still called as a
    fallback for any combinations that don't exist yet, so tasks are still
    created on demand when build_extract_tasks hasn't run yet and concurrent
    IntegrityErrors are still handled correctly.
    """
    all_task_ids: dict[int, int] = {}
    valid_datasets: list[dict] = []

    for resolved in plan.resolved:
        task_kwargs = resolved.task_kwargs
        fm_ids = [fm.id for fm in resolved.fms]
        po_ids = [po.id for po in resolved.pos]
        all_resource_ids = [r.id for r in resolved.resources]

        # One query to fetch all pre-existing tasks for this dataset × the
        # requested (fm, resource, po) space. resource_ids__overlap narrows to
        # rows that share at least one element with the requested resources;
        # the dict key (fm_id, tuple(resource_ids), po_id) enforces exact match.
        qs = ExtractTask.objects.filter(
            dataset_id=resolved.dataset.id,
            fm_id__in=fm_ids,
            po_id__in=po_ids,
            resource_ids__overlap=all_resource_ids,
        )
        if task_kwargs is None:
            qs = qs.filter(kwargs__isnull=True)
        else:
            qs = qs.filter(kwargs=task_kwargs)

        existing: dict[tuple, int] = {}
        to_bump: list[int] = []
        for t in qs.only("id", "fm_id", "resource_ids", "po_id", "priority"):
            key = (t.fm_id, tuple(t.resource_ids), t.po_id)
            existing[key] = t.id
            if t.priority < 1:
                to_bump.append(t.id)

        # Single UPDATE for all low-priority existing tasks. dataset_id
        # included (redundant with id, which is already unique) so Postgres
        # prunes to this one partition instead of scanning all of them --
        # extract_tasks is LIST partitioned on dataset_id, and an UPDATE
        # filtered by id alone doesn't get the same partition-constraint
        # propagation a SELECT does. See claim_pending_tasks' docstring in
        # analytics/tasks/processing.py for the fully worked-out example
        # (0.2ms pruned vs 4.1s unpruned, measured against production).
        if to_bump:
            ExtractTask.objects.filter(
                id__in=to_bump, dataset_id=resolved.dataset.id
            ).update(priority=1)

        task_ids = []
        for fm in resolved.fms:
            for resource in resolved.resources:
                for po in resolved.pos:
                    key = (fm.id, (resource.id,), po.id)
                    if key in existing:
                        task_ids.append(existing[key])
                    else:
                        # Not pre-built yet — create on demand, race-safe.
                        task = _get_or_create_task(resolved, fm, resource, po)
                        if task.priority < 1:
                            # Explicit filter, not task.save() -- save()
                            # would only filter by id, hitting the same
                            # unpruned-scan cost as the bulk update above,
                            # except once per task instead of once per
                            # request. This is the actual hot path: every
                            # task that isn't pre-built yet pays this,
                            # sequentially, inside one long transaction.
                            ExtractTask.objects.filter(
                                id=task.id, dataset_id=task.dataset_id
                            ).update(priority=1)
                            task.priority = 1
                        task_ids.append(task.id)

        all_task_ids.update({tid: resolved.dataset.id for tid in task_ids})
        ds = resolved.spec
        valid_datasets.append(
            {
                "dataset_name": resolved.dataset.name,
                "dataset_type": (ds.get("datasetType") or "").strip() or None,
                "extract_types": ds.get("extractTypes") or [],
                "resources": ds.get("resources") or [],
                "resource_labels": ds.get("resourceLabels") or [],
                "kwargs": resolved.task_kwargs,
            }
        )

    return all_task_ids, valid_datasets


def create_request(
    *,
    user,
    contact: str,
    name: str | None,
    feature_ids: list[int],
    datasets: list[dict],
    selection_label: str | None = None,
    selection_detail: str | None = None,
    source: str = "web",
) -> CreatedRequest:
    """Create a Request at status=4 (materializing) and defer ExtractTask/
    RequestMap creation to a background task.

    Validates the submission synchronously -- resolve_request_plan is
    read-only and already exposes task_count, so a bad dataset name or an
    empty selection still fails the request immediately, exactly as before.
    Only the expensive per-task materialization work (_build_tasks, one DB
    round-trip per (feature, resource, option) triple that isn't already
    pre-built) moves to the background -- a submission spanning enough
    time-series datasets can touch tens of thousands of triples, which was
    taking long enough to 504 even after the per-triple DB operations
    themselves were fixed to be fast (see analytics/tasks/processing.py and
    the resource_ids_hash partition-pruning fixes).

    Saving the Request fires the post_save receiver in analytics.signals,
    which is harmless at status=4: the completion sweep only ever looks at
    status=-1/0 (manage_user_requests.py), so it simply finds nothing to do
    for this request yet. The real "go process this" trigger is
    materialize_request_tasks firing the same dispatch chain once
    materialization finishes and the request becomes visible to the sweep
    for the first time.
    """
    plan = resolve_request_plan(user, feature_ids, datasets)

    if not plan.resolved:
        raise NoExtractTasksError(plan.warnings)

    req = Request.objects.create(
        contact=contact,
        custom_name=name or None,
        user=user,
        source=source,
        status=4,
        data={
            "selection_label": selection_label,
            "selection_detail": selection_detail,
            "feature_ids": feature_ids,
            "datasets": [],
            "dataset_specs": datasets,
        },
    )

    # Deferred import: analytics.tasks.requests imports materialize_request
    # from this module, so a top-level import here would be circular. Same
    # pattern analytics.signals already uses for analytics.tasks.maintenance.
    from analytics.tasks.requests import materialize_request_tasks

    transaction.on_commit(lambda: materialize_request_tasks.delay(str(req.id)))

    return CreatedRequest(
        request=req, task_count=plan.task_count, warnings=plan.warnings
    )


def materialize_request(request: Request) -> None:
    """The deferred half of create_request: build ExtractTasks, create
    RequestMap rows, and move the request from status=4 (materializing) to
    status=-1 (queued) -- the transition that makes it visible to the
    completion sweep for the first time.

    Re-resolves the plan against current state (feature_ids and
    dataset_specs, both stored on the request at submission time) rather
    than trusting a stale snapshot: dataset/feature visibility could
    theoretically change in the gap between submission and this running.
    Raises NoExtractTasksError if nothing resolves anymore -- the caller
    (materialize_request_tasks) is responsible for turning that into a
    status=-2 error on the request, the same way create_request turns it
    into an HTTP 400 when it happens synchronously at submission time.

    Idempotent: deletes any RequestMap rows already attached to this request
    before recreating them. A single background task owns materializing a
    given request (enforced by the status=4 -> -1 gate), but Celery broker
    redelivery -- or someone manually re-triggering a stuck request -- can
    still run this twice for the same request_id. Without the delete, a
    second run would duplicate every RequestMap row: there's no unique
    constraint on (request, task), and _check_request_tasks in
    manage_user_requests.py computes the completion total from a
    non-deduplicated task list, so a duplicated set would permanently
    inflate total relative to completed and the request could never finish.
    """
    plan = resolve_request_plan(
        request.user, request.data["feature_ids"], request.data["dataset_specs"]
    )
    all_task_ids, valid_datasets = _build_tasks(plan)

    if not all_task_ids:
        raise NoExtractTasksError(plan.warnings)

    RequestMap.objects.filter(request=request).delete()
    RequestMap.objects.bulk_create(
        [
            RequestMap(request=request, task_id=task_id, dataset_id=dataset_id)
            for task_id, dataset_id in all_task_ids.items()
        ]
    )

    Request.objects.filter(id=request.id).update(
        status=-1,
        data={**request.data, "datasets": valid_datasets},
    )


def requests_for_user(user) -> QuerySet[Request]:
    """Every request belonging to ``user``, newest first.

    Union of FK-claimed rows and live contact matches on verified emails, so
    the list is correct even before a claim sweep runs. Shared with
    ``MyRequestsView`` so the web history and the MCP export list can never
    disagree about what someone owns.
    """
    from allauth.account.models import EmailAddress

    q = Q(user=user)
    emails = EmailAddress.objects.filter(user=user, verified=True).values_list(
        "email", flat=True
    )
    for email in emails:
        q |= Q(contact__iexact=email)

    return Request.objects.filter(q).order_by("-submit_time")


def request_progress(request: Request) -> tuple[int, int]:
    """``(completed_tasks, total_tasks)`` for a request.

    Delegates to the same check the completion sweep runs, in dry-run mode so
    it neither bumps priorities nor writes anything -- reading a status must
    not change what the workers do next.
    """
    from analytics.management.commands.manage_user_requests import _check_request_tasks

    pending, completed = _check_request_tasks(request, dry_run=True)
    return len(completed), len(completed) + pending


def request_links(request: Request) -> dict:
    """Download, documentation and visualization URLs for a completed request.

    Empty until the request completes: the zip and the documentation page do
    not exist before then, and a link to a half-built visualization is worse
    than no link. Each base URL is checked independently because a deployment
    may configure one and not the other.
    """
    if request.status != 1:
        return {}

    links: dict[str, str] = {}
    base = getattr(settings, "DOWNLOAD_BASE_URL", "").rstrip("/")
    if base:
        links["download_url"] = f"{base}/requests/{request.id}/{request.id}.zip"
        links["documentation_url"] = (
            f"{base}/requests/{request.id}/{request.id}_documentation.html"
        )
    frontend_base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
    if frontend_base:
        links["visualization_url"] = f"{frontend_base}/viz/{request.id}"
    return links
