"""Exports: previewing, submitting, and following a request.

An export is the only thing this server creates, and it is expensive -- it
occupies the processing workers and produces a permanent, publicly readable
artifact. So ``submit_request`` never fires on the model's say-so alone: it
asks the user, through the client, and only creates the Request once they have
seen the actual cost and agreed to it.

Everything here goes through ``analytics.services``, the same code path the
website's submit button uses, so an MCP export is indistinguishable from a web
export except for ``Request.source``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from django.conf import settings
from fastmcp import Context
from mcp import types as mcp_types
from fastmcp.tools import InputRequiredToolResult
from pydantic import Field

from analytics.models import ExtractTask, Request
from analytics.services import (
    STATUS_LABELS,
    NoExtractTasksError,
    create_request,
    request_links,
    request_progress,
    requests_for_user,
    resolve_request_plan,
)
from catalog.access import visible_feature_collections
from mcp_server.data.attribution import attribution_for_request
from mcp_server.data.selection import SelectionError, get_request_or_error
from mcp_server.schemas import DatasetSpec

from .common import READ_ONLY, fmt_count, require_user, result, tool_body

# Key under which the confirmation question is sent and its answer read back.
_CONFIRM = "confirm"


def _to_web_spec(spec: dict) -> dict:
    """Translate the model-facing DatasetSpec into the web submission shape.

    analytics.services speaks camelCase because the browser does; the model is
    given snake_case because that is what it writes correctly. The mapping
    lives here so neither side has to compromise.
    """
    name = (spec.get("name") or "").strip()
    if not name:
        raise SelectionError(
            "Each dataset needs a 'name', e.g. {'name': 'esa_landcover', "
            "'extract_types': ['mean']}."
        )
    return {
        "datasetName": name,
        "extractTypes": spec.get("extract_types") or [],
        "resources": spec.get("resources") or [],
        "kwargs": spec.get("kwargs") or None,
    }


def _resolve_feature_ids(user, boundary: str) -> tuple[list[int], object]:
    from features.models import FeatMap

    fc = visible_feature_collections(user).filter(name=boundary).first()
    if fc is None:
        raise SelectionError(
            f"No boundary available named '{boundary}'. Use search_boundaries "
            "to find the exact name."
        )
    ids = list(
        FeatMap.objects.filter(fc=fc).values_list("geom_id", flat=True).distinct()
    )
    if not ids:
        raise SelectionError(f"Boundary '{boundary}' has no features to extract.")
    return ids, fc


def _plan(user, boundary: str, datasets: list[dict], feature_ids=None):
    all_ids, fc = _resolve_feature_ids(user, boundary)
    if feature_ids:
        chosen = [i for i in feature_ids if i in set(all_ids)]
        if not chosen:
            raise SelectionError(
                f"None of the given feature_ids belong to '{boundary}'. Use "
                "get_boundary to see its feature ids."
            )
        all_ids = chosen
    specs = [_to_web_spec(d) for d in datasets]
    return resolve_request_plan(user, all_ids, specs), all_ids, fc, specs


def _already_processed(plan, feature_ids: list[int]) -> float:
    """Share of the planned tasks that already exist and are finished.

    Reused tasks make an export nearly instant, so this is the single most
    useful number in a preview: "90% already done" and "0% already done" are
    minutes versus days, and the user should be told which they are choosing.
    """
    if not plan.resolved:
        return 0.0
    total = plan.task_count
    if not total:
        return 0.0
    done = 0
    for resolved in plan.resolved:
        done += ExtractTask.objects.filter(
            dataset_id=resolved.dataset.id,
            fm__geom_id__in=feature_ids,
            po_id__in=[po.id for po in resolved.pos],
            status=1,
        ).count()
    return round(min(done, total) / total, 3)


def _plan_hash(boundary: str, specs: list[dict], feature_ids: list[int]) -> str:
    """Fingerprint of what the user was actually shown.

    The confirmation round trip carries this back; if the retry's arguments
    hash differently, the model changed the request between asking and
    submitting, and the consent no longer covers it.
    """
    blob = json.dumps(
        {"boundary": boundary, "datasets": specs, "features": sorted(feature_ids)},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _preview_request(user, boundary: str, datasets: list[dict], feature_ids=None) -> dict:
    plan, ids, fc, _specs = _plan(user, boundary, datasets, feature_ids)
    return {
        "boundary": fc.name,
        "boundary_title": fc.title or fc.name,
        "feature_count": len(ids),
        "task_count": plan.task_count,
        "already_processed": _already_processed(plan, ids),
        "datasets": [
            {
                "name": r.dataset.name,
                "title": r.dataset.title or r.dataset.name,
                "extract_types": [po.short_name for po in r.pos],
                "resource_count": len(r.resources),
                "task_count": r.task_count,
            }
            for r in plan.resolved
        ],
        "warnings": plan.warnings,
        "over_limit": plan.task_count > settings.MCP_SUBMIT_MAX_TASKS,
        "attribution": _plan_attribution(plan, fc),
    }


def _plan_attribution(plan, fc) -> dict:
    from mcp_server.data.attribution import attribution_for

    return attribution_for([r.dataset for r in plan.resolved], [fc])


def _status_payload(request: Request) -> dict:
    completed, total = request_progress(request)
    return {
        "request_id": str(request.id),
        "name": request.custom_name,
        "status": request.status,
        "status_label": STATUS_LABELS.get(request.status, "unknown"),
        "submitted": request.submit_time.isoformat() if request.submit_time else None,
        "completed": request.complete_time.isoformat()
        if request.complete_time
        else None,
        "tasks_completed": completed,
        "tasks_total": total,
        "progress": round(completed / total, 3) if total else 0.0,
        **request_links(request),
        "attribution": attribution_for_request(request),
    }


def _get_request_status(user, request_id: str) -> dict:
    return _status_payload(
        get_request_or_error(request_id, "Use list_my_requests to see your exports.")
    )


def _list_my_requests(user, limit=20, offset=0, status=None) -> dict:
    qs = requests_for_user(require_user(user))
    if status is not None:
        qs = qs.filter(status=status)
    total = qs.count()
    rows = list(qs[offset : offset + max(1, limit)])
    return {
        "requests": [
            {
                "request_id": str(r.id),
                "name": r.custom_name,
                "status": r.status,
                "status_label": STATUS_LABELS.get(r.status, "unknown"),
                "submitted": r.submit_time.isoformat() if r.submit_time else None,
                **request_links(r),
            }
            for r in rows
        ],
        "total": total,
        "offset": offset,
        "truncated": offset + len(rows) < total,
    }


def _confirmation_request(summary: str) -> mcp_types.ElicitRequest:
    return mcp_types.ElicitRequest(
        params=mcp_types.ElicitRequestFormParams(
            message=summary,
            requested_schema={
                "type": "object",
                "properties": {
                    _CONFIRM: {
                        "type": "boolean",
                        "title": "Create this export?",
                        "description": "It will be processed in the background.",
                    }
                },
                "required": [_CONFIRM],
            },
        )
    )


def _preview_summary(preview: dict) -> str:
    parts = [
        f"Create an export of {preview['boundary_title']} "
        f"({fmt_count(preview['feature_count'], 'feature')}) covering "
        + ", ".join(d["title"] for d in preview["datasets"])
        + "?",
        f"{fmt_count(preview['task_count'], 'extraction')} in total; "
        f"{preview['already_processed']:.0%} already processed.",
    ]
    if preview["warnings"]:
        parts.append("Warnings: " + " ".join(preview["warnings"]))
    return "\n".join(parts)


def _accepted(answer) -> bool:
    """Did the user actually say yes?

    Both halves are load-bearing: a client may return ``action="accept"`` with
    the box unticked, and a declining client may return an object with no
    content at all. Anything that is not an unambiguous yes is a no.
    """
    if getattr(answer, "action", None) != "accept":
        return False
    content = getattr(answer, "content", None) or {}
    return bool(content.get(_CONFIRM))


def _supports_elicitation(ctx: Context) -> bool:
    """Can this client show the user a confirmation prompt?

    Not every client implements elicitation. Returning an InputRequiredResult
    to one that does not is a hard error the user cannot act on, so those
    clients get the `confirm=True` argument route instead.
    """
    try:
        return bool(
            ctx.session.check_client_capability(
                mcp_types.ClientCapabilities(elicitation=mcp_types.ElicitationCapability())
            )
        )
    except Exception:
        return False


def register(mcp, user_dep):
    @mcp.tool(annotations=READ_ONLY)
    @tool_body
    def preview_request(
        boundary: Annotated[
            str, Field(description="Feature collection name from search_boundaries.")
        ],
        datasets: Annotated[
            list[DatasetSpec],
            Field(description="Datasets to extract, e.g. [{'name': 'esa_landcover'}]."),
        ],
        feature_ids: Annotated[
            list[int] | None,
            Field(
                description=(
                    "Restrict to specific features of the boundary. Omit for all "
                    "of them."
                )
            ),
        ] = None,
        user=user_dep,
    ):
        """What an export would produce, without creating anything.

        Show the user `task_count` and `already_processed` before offering to
        submit: an export that is mostly already processed finishes in
        minutes, one that is not can take hours. `warnings` lists anything in
        the selection that would be silently skipped.
        """
        payload = _preview_request(user, boundary, datasets, feature_ids)
        lines = [
            f"Would create {fmt_count(payload['task_count'], 'extraction')} over "
            f"{fmt_count(payload['feature_count'], 'feature')} of "
            f"{payload['boundary_title']}; "
            f"{payload['already_processed']:.0%} already processed.",
        ]
        for ds in payload["datasets"]:
            lines.append(
                f"- {ds['name']} [{', '.join(ds['extract_types'])}] × "
                f"{fmt_count(ds['resource_count'], 'resource')} = "
                f"{ds['task_count']:,} extractions"
            )
        lines.extend(payload["warnings"])
        if payload["over_limit"]:
            lines.append(
                f"This exceeds the {settings.MCP_SUBMIT_MAX_TASKS:,}-extraction "
                "limit and cannot be submitted. Narrow the boundary, the years, "
                "or the extract types."
            )
        return result(lines, payload)

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
    )
    @tool_body
    def submit_request(
        boundary: Annotated[str, Field(description="Feature collection name.")],
        datasets: Annotated[
            list[DatasetSpec], Field(description="Datasets to extract.")
        ],
        name: Annotated[
            str, Field(description="A short name for this export, shown to the user.")
        ],
        feature_ids: Annotated[
            list[int] | None,
            Field(description="Restrict to specific features. Omit for all."),
        ] = None,
        confirm: Annotated[
            bool,
            Field(
                description=(
                    "Leave false. The user is asked to confirm directly. Only "
                    "set true if a previous call told you to, having shown the "
                    "user the preview yourself."
                )
            ),
        ] = False,
        ctx: Context = None,
        user=user_dep,
    ):
        """Create a permanent, downloadable export of a data selection.

        This starts real processing and produces a shareable artifact, so the
        user is asked to confirm before anything is created -- call it
        directly; do not ask them yourself first.

        Use this only when the user wants a file, a permanent link, or a
        reproducible record. To answer a question or draw a map, use get_data
        or show_map instead: those need no waiting.
        """
        require_user(user)
        preview = _preview_request(user, boundary, datasets, feature_ids)
        specs = [_to_web_spec(d) for d in datasets]
        ids, fc = _resolve_feature_ids(user, boundary)
        if feature_ids:
            ids = [i for i in feature_ids if i in set(ids)]
        expected_hash = _plan_hash(boundary, specs, ids)

        if preview["over_limit"]:
            raise SelectionError(
                f"This export would create {preview['task_count']:,} extractions, "
                f"over the {settings.MCP_SUBMIT_MAX_TASKS:,} limit. Narrow the "
                "boundary, the years, or the extract types."
            )
        if not preview["task_count"]:
            raise SelectionError(
                "Nothing to extract for this selection. "
                + " ".join(preview["warnings"])
            )

        answers = ctx.input_responses if ctx else None
        if not answers and not confirm:
            if ctx and not _supports_elicitation(ctx):
                # No way to ask the user directly. Hand the model the numbers
                # and make it get consent in the conversation instead.
                return result(
                    [
                        "Not submitted yet — this client cannot show a "
                        "confirmation prompt.",
                        _preview_summary(preview),
                        "Show these numbers to the user. If they agree, call "
                        "submit_request again with confirm=true and exactly "
                        "these arguments.",
                    ],
                    preview,
                )
            return InputRequiredToolResult(
                mcp_types.InputRequiredResult(
                    input_requests={_CONFIRM: _confirmation_request(_preview_summary(preview))},
                    request_state=expected_hash,
                )
            )

        if answers:
            if not _accepted(answers.get(_CONFIRM)):
                return result(
                    ["Cancelled. Nothing was submitted."],
                    {"cancelled": True, "attribution": preview["attribution"]},
                )
            # The consent was for the plan shown a moment ago. If the
            # arguments changed in between, it does not transfer.
            if ctx.request_state and ctx.request_state != expected_hash:
                raise SelectionError(
                    "The export changed after the user confirmed it. Call "
                    "preview_request again and re-confirm."
                )

        try:
            created = create_request(
                user=user,
                contact=user.email,
                name=name,
                feature_ids=ids,
                datasets=specs,
                selection_label=fc.title or fc.name,
                selection_detail=f"{len(ids)} features",
                source="mcp",
            )
        except NoExtractTasksError as exc:
            raise SelectionError(
                "No extract tasks could be created. " + " ".join(exc.warnings)
            ) from exc

        payload = {
            **_status_payload(created.request),
            "task_count": created.task_count,
            "warnings": created.warnings,
        }
        lines = [
            f"Export '{name}' submitted ({fmt_count(created.task_count, 'extraction')}).",
            f"Follow it with get_request_status('{created.request.id}').",
            *created.warnings,
        ]
        return result(lines, payload)

    @mcp.tool(annotations=READ_ONLY)
    @tool_body
    def get_request_status(
        request_id: Annotated[str, Field(description="Export id.")],
        user=user_dep,
    ):
        """Progress of an export, and its links once it finishes.

        A completed export gains `download_url` (the zip), `documentation_url`
        (its citations and licenses) and `visualization_url`. Its results can
        also be read directly with get_data or show_map using `request_id`.
        """
        payload = _get_request_status(user, request_id)
        lines = [
            f"{payload['name'] or payload['request_id'][:8]}: "
            f"{payload['status_label']} — {payload['tasks_completed']:,}/"
            f"{payload['tasks_total']:,} extractions done."
        ]
        if payload.get("download_url"):
            lines.append(f"Download: {payload['download_url']}")
            lines.append(f"Documentation (citations, licenses): {payload['documentation_url']}")
        return result(lines, payload)

    @mcp.tool(annotations=READ_ONLY)
    @tool_body
    def list_my_requests(
        limit: Annotated[int, Field(description="Maximum results.", ge=1, le=100)] = 20,
        offset: Annotated[int, Field(description="Results to skip.", ge=0)] = 0,
        status: Annotated[
            int | None,
            Field(
                description=(
                    "Filter by status: 1 completed, 0 processing, -1 queued, "
                    "-2 error."
                )
            ),
        ] = None,
        user=user_dep,
    ):
        """The signed-in user's exports, newest first.

        Includes exports made on the GeoQuery website under any verified email
        on the account, not only those created here.
        """
        payload = _list_my_requests(user, limit, offset, status)
        lines = [f"{fmt_count(payload['total'], 'export')}."]
        for r in payload["requests"]:
            lines.append(
                f"- {r['request_id'][:8]} {r['name'] or '(unnamed)'}: "
                f"{r['status_label']}"
            )
        # No data leaves the server here -- just the user's own export list --
        # so this is the one tool with no attribution to relay.
        from fastmcp.tools import ToolResult

        return ToolResult(content="\n".join(lines), structured_content=payload)
