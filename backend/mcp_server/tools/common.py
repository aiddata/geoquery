"""Plumbing shared by every tool module.

Three things belong here rather than in each tool: releasing the database
connection, turning the data layer's exceptions into errors the model can
read, and making sure the attribution line is on the end of the text a tool
returns. Each is easy to forget once per tool and expensive to get wrong -- a
swallowed ``SelectionError`` becomes an opaque "tool failed", a dropped
attribution line is how a license requirement quietly disappears from a
conversation, and a leaked connection takes the whole server down after a few
thousand calls.
"""

from __future__ import annotations

import functools

from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations

from mcp_server.auth import AuthenticationRequired
from mcp_server.data.selection import SelectionError
from mcp_server.db import django_db

# Every tool in this server reads; none mutate anything the caller can
# observe except submit_request. Stated explicitly so a client can decide
# what to auto-approve.
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def tool_body(fn):
    """Wrap a tool body: manage its connection, and report its errors usefully.

    The connection handling has to happen here, not in a ``Depends()``, because
    only this wrapper runs in the same thread as the query -- see
    ``mcp_server.db.django_db``.

    Error translation: FastMCP masks unexpected exceptions behind a generic
    failure message, which is the right default but exactly wrong for these
    two. A selection that cannot be resolved, or a caller with no account, are
    both things the model can fix on its next turn -- if it is told what
    happened.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with django_db():
            try:
                return fn(*args, **kwargs)
            except (SelectionError, AuthenticationRequired) as exc:
                raise ToolError(str(exc)) from exc

    return wrapper


def text_with_attribution(lines: list[str], attribution: dict) -> str:
    """Join a tool's text content and end it with the attribution line."""
    body = [line for line in lines if line]
    body.append(attribution["text"])
    return "\n".join(body)


def result(lines: list[str], structured: dict) -> ToolResult:
    """A ToolResult whose text ends with the attribution from its own payload.

    Taking the attribution out of ``structured`` rather than as a separate
    argument means the text and the structured content can never disagree
    about what is being cited.
    """
    return ToolResult(
        content=text_with_attribution(lines, structured["attribution"]),
        structured_content=structured,
    )


def require_user(user):
    """Reject an anonymous caller for a tool that needs an account."""
    if user is None:
        raise AuthenticationRequired(
            "This action needs a signed-in GeoQuery account. Reconnect the "
            "server and complete the GitHub sign-in."
        )
    return user


def fmt_count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n:,} {singular if n == 1 else (plural or singular + 's')}"
