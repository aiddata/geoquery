"""Resources: boundary presets, results CSV, and the citation guide.

Resources are what a client can pull in without the model having to ask, so
these are the things worth having to hand: the canned boundary selections the
website offers, the raw rows of a finished export, and GeoQuery's citation
policy.
"""

from __future__ import annotations

import csv
import io

from asgiref.sync import sync_to_async
from django.conf import settings

from mcp_server.data.attribution import attribution_for_request
from mcp_server.data.selection import SelectionError, get_request_or_error
from mcp_server.db import django_db

BOUNDARY_PRESETS_URI = "geoquery://boundary-presets"
RESULTS_CSV_URI = "geoquery://requests/{request_id}/results.csv"
CITING_URI = "geoquery://citing"


def _attribution_header(attribution: dict) -> list[str]:
    """Comment lines prefixed to the CSV.

    A CSV gets detached from its conversation the moment it is saved, so the
    attribution has to travel inside the file. ``#`` comments are ignored by
    pandas (``comment='#'``), R and Excel's import wizard, and are the
    convention the scientific-data world already reads.
    """
    lines = ["# Data retrieved from GeoQuery (https://www.geoquery.org)"]
    for item in (*attribution["datasets"], *attribution["boundaries"]):
        lines.append(f"# Source: {item['title']} — {item['source_name'] or 'unknown'}")
        lines.append(f"# License: {item['license'] or 'not recorded; check the source'}")
        lines.append(
            f"# Citation: {item['citation'] or 'not recorded; cite the source above'}"
        )
    lines.append(f"# Cite GeoQuery: {attribution['geoquery']['citation']}")
    return lines


def _results_csv(request_id: str) -> str:
    from visualize.data import build_request_data

    request = get_request_or_error(
        request_id, "Use list_my_requests to see your exports."
    )
    if request.status != 1:
        raise SelectionError(
            f"Request {request_id} has not finished; its results are not "
            "readable yet."
        )

    payload = build_request_data(request)
    columns = payload["columns"]
    buffer = io.StringIO()
    for line in _attribution_header(attribution_for_request(request)):
        buffer.write(line + "\n")

    writer = csv.writer(buffer)
    writer.writerow(["feature_id", "name", "boundary", *columns])
    for geom_id, record in sorted(payload["features"].items(), key=lambda kv: kv[1].get("name") or ""):
        writer.writerow(
            [geom_id, record.get("name"), record.get("fc"), *(record.get(c) for c in columns)]
        )
        # Checked as we go rather than at the end: a 200k-feature export would
        # otherwise be fully materialized in memory before being rejected.
        if buffer.tell() > settings.MCP_RESULTS_CSV_MAX_BYTES:
            links = []
            base = getattr(settings, "DOWNLOAD_BASE_URL", "").rstrip("/")
            if base:
                links.append(f"{base}/requests/{request.id}/{request.id}.zip")
            buffer.write(
                "# Truncated: this export is larger than "
                f"{settings.MCP_RESULTS_CSV_MAX_BYTES // (1024 * 1024)} MB. "
                + (f"Download the full results at {links[0]}\n" if links else "\n")
            )
            break
    return buffer.getvalue()


# Unlike tools, FastMCP runs resource functions on the event loop, where the
# Django ORM refuses to run at all ("You cannot call this from an async
# context"). Every resource that touches the database therefore hands its body
# to a worker thread. thread_sensitive=False gives each call its own thread and
# its own connection, matching how tools already behave.
_in_thread = sync_to_async(lambda fn: fn(), thread_sensitive=False)


def register(mcp, user_dep):
    @mcp.resource(
        BOUNDARY_PRESETS_URI,
        name="Boundary presets",
        description=(
            "Named boundary selections offered on the GeoQuery website, e.g. "
            "'All countries' or 'African ADM1'."
        ),
        mime_type="application/json",
    )
    async def boundary_presets() -> list:
        from features.views import BoundaryPresetsView

        def read():
            # No Depends() here: a resource's parameters are its URI template
            # variables, so an injected one would change the URI it answers
            # to. The connection still has to be released -- see mcp_server.db.
            with django_db():
                return BoundaryPresetsView._load_presets()

        return await _in_thread(read)

    @mcp.resource(
        RESULTS_CSV_URI,
        name="Export results (CSV)",
        description=(
            "The rows of a finished export, with source, license and citation "
            "as comment lines above the header."
        ),
        mime_type="text/csv",
    )
    async def results_csv(request_id: str) -> str:
        def read():
            with django_db():
                return _results_csv(request_id)

        return await _in_thread(read)

    @mcp.resource(
        CITING_URI,
        name="Citing GeoQuery",
        description="How to cite GeoQuery and the datasets it redistributes.",
        mime_type="text/markdown",
    )
    def citing() -> str:
        path = settings.DOCS_DIR / "citing.md"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            # The docs directory is not mounted into every deployment of this
            # image, so fall back rather than failing: the citation itself is
            # the part that matters and it is compiled in.
            from geoquery.citations import GEOQUERY_CITATION

            return (
                "# Citing GeoQuery\n\n"
                "Cite the GeoQuery paper, plus every dataset and boundary you "
                "used — see the `attribution` in any tool result, or call "
                "`get_citations`.\n\n"
                f"> {GEOQUERY_CITATION}\n"
            )
