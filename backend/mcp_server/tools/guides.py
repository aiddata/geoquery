"""get_guide: the body of one of the guides SERVER_INSTRUCTIONS advertises.

Registered only when there are guides to serve -- a tool whose every call
would be an error is worse than no tool, and the model is told about guides by
the instructions, which are generated from the same directory.
"""

#
# Deliberately without ``from __future__ import annotations``, unlike its
# sibling modules: the argument description below is built from the guides on
# disk, and a deferred annotation is evaluated by pydantic against this
# module's globals, where that local does not exist. Eager evaluation resolves
# it from the enclosing scope. (``tools.map`` gets away with the future import
# because the value it interpolates, PALETTES, is a module-level import.)

from typing import Annotated

from fastmcp.tools import ToolResult
from pydantic import Field

from mcp_server.data.guides import available_guides, load_guide
from mcp_server.schemas import GENERIC_OUTPUT_SCHEMA

from .common import READ_ONLY, tool_body


def register(mcp, user_dep):
    guides = available_guides()
    if not guides:
        return

    # Named in the argument description rather than left to the instructions:
    # a model that reaches this tool at all should not have to scroll back to
    # find out which names it accepts.
    known = ", ".join(f"'{guide.name}'" for guide in guides)

    @mcp.tool(annotations=READ_ONLY, output_schema=GENERIC_OUTPUT_SCHEMA)
    @tool_body
    def get_guide(
        name: Annotated[str, Field(description=f"Which guide to read: {known}.")],
    ):
        """Read one of GeoQuery's guides: longer instructions for a kind of
        work the server expects to be done a particular way.

        The server instructions list each guide and when it applies. Read the
        guide before starting that work -- its rules shape what you build,
        so applying them afterwards means redoing it.
        """
        # No `user`: guides are the same for everyone, and taking the
        # dependency would make every call resolve an account it never reads.
        guide = load_guide(name)
        # The body goes in the text content and nowhere else. Everything else
        # in this server mirrors its structured payload into text because
        # clients vary in what they forward to the model (see tools.common);
        # here the markdown *is* the payload, so mirroring it would just send
        # several KB twice. The structured half carries only the metadata a
        # client needs to label what it got.
        # The body is returned as written, with no heading prepended: a guide
        # opens with its own H1, and a second one above it reads as two
        # documents.
        return ToolResult(
            content=guide.body,
            structured_content={
                "name": guide.name,
                "title": guide.title,
                "description": guide.description,
                "when": guide.when,
            },
        )
