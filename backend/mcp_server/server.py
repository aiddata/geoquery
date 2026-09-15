"""The GeoQuery MCP server.

``build_server`` is a factory rather than a module-level singleton so tests can
stand up a server with authentication off and a fixed user, and so the
management command can decide at startup whether to require GitHub OAuth. Both
paths register the same tools against the same database.
"""

from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP

SERVER_NAME = "GeoQuery"

SERVER_INSTRUCTIONS = """\
GeoQuery gives you geospatial data aggregated to administrative boundaries:
satellite, climate, conflict, aid and infrastructure datasets summarised per
district, province or country.

There are two ways to work with it, and the difference matters.

EXPLORE (instant). Most of GeoQuery's boundary x dataset combinations are
already processed and can be read immediately. This is the right path for
answering a question, making a chart, or drawing a map:
    search_boundaries  -> find the exact boundary names for a place
    list_available_data -> see what is already processed for those boundaries
    get_data           -> actual table/GeoJSON values for analysis or your own visualisation
    show_map           -> an interactive choropleth rendered directly in the chat
Use this first. It needs no waiting and no submission.

Use get_data when you need to calculate, compare, quote, or inspect values.
Its text includes a JSON copy for clients that do not expose structured
content. Use show_map when the user wants to see spatial patterns; the client
receives a purpose-built map app and the model receives a compact summary.

EXPORT (asynchronous, permanent). Turning a selection into a downloadable,
citable artifact -- a zip with CSV, GeoPackage, documentation and notebook
links -- takes minutes to hours:
    preview_request -> what would be built, and how much of it already exists
    submit_request  -> create the export (asks the user to confirm first)
    get_request_status -> progress, then the download link
Offer an export when the user wants a file, a shareable permanent link, or a
reproducible record -- not merely to answer a question. A finished export can
be read back through get_data and show_map with request_id=.

ATTRIBUTION. GeoQuery redistributes open data under its original licenses.
Every result that carries data includes an `attribution` object. When you
present GeoQuery data, name each dataset and boundary source, its license,
and its academic citation from `attribution`, and cite GeoQuery itself. Do
not summarise data while dropping its attribution. Use get_citations for a
formatted reference list, and tell the user when a license or citation is
recorded as missing -- that means they must check the source themselves
before publishing.

Results are capped in size on purpose. When a result comes back truncated,
narrow the selection (fewer boundaries, fewer years, one extract type) rather
than paging through everything -- or hand the user the `viz_url` in the
result, which opens the full selection in GeoQuery's own map.
"""


def build_server(
    *,
    auth=None,
    user_resolver: Callable[[], object] | None = None,
) -> FastMCP:
    """Construct the server.

    ``user_resolver`` returns the ``accounts.User`` a tool call acts as. In
    production it reads the OAuth access token (see ``mcp_server.auth``); tests
    pass a lambda returning a fixture user; unauthenticated local development
    passes one returning ``None``, which every tool treats as an anonymous
    caller -- public data only, no exports.
    """
    from .tools import register_all

    mcp = FastMCP(
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        auth=auth,
    )
    register_all(mcp, user_resolver=user_resolver)
    return mcp
