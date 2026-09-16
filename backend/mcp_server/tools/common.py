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

import csv
import functools
import io
import json

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


def json_block(structured: dict) -> str:
    """The whole payload, mirrored into the text content as JSON.

    Many clients never hand ``structuredContent`` to the model, so a tool that
    puts its data only there has, from the model's side, returned nothing. The
    spec's own advice is to mirror it, and for the small catalog payloads JSON
    is the right shape to mirror in.
    """
    serialized = json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
    return f"Structured data (JSON):\n```json\n{serialized}\n```"


def csv_block(header: list[str], rows) -> str:
    """Tabular data as CSV, for the text content block.

    ``get_data`` returns the one payload big enough for the mirroring to cost
    real context, and a table of numbers is several times cheaper as CSV than
    as JSON -- no repeated key per cell. ``csv`` also writes floats through
    ``repr``, so a value reaches the model at full precision rather than the
    four significant figures a display format would leave it with.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return "```csv\n" + buffer.getvalue().rstrip("\n") + "\n```"


def result(
    lines: list[str],
    structured: dict,
    *,
    data_block: str | None = None,
    meta: dict | None = None,
) -> ToolResult:
    """A ToolResult whose text ends with the attribution from its own payload.

    Taking the attribution out of ``structured`` rather than as a separate
    argument means the text and the structured content can never disagree
    about what is being cited.

    ``data_block`` overrides the default JSON mirror for tools that have a
    cheaper serialization of their own -- see ``csv_block``.
    """
    text = text_with_attribution(
        [*lines, data_block if data_block is not None else json_block(structured)],
        structured["attribution"],
    )
    return ToolResult(
        content=text,
        structured_content=structured,
        meta=meta,
    )


def plain_result(lines: list[str], structured: dict) -> ToolResult:
    """Return non-attributed structured data with a text JSON fallback."""
    return ToolResult(
        content="\n".join([*lines, json_block(structured)]),
        structured_content=structured,
    )


def fmt_number(value) -> str:
    """A number as a person would write it, never in scientific notation.

    ``{:.4g}`` turns a population of 18,054,321 into ``1.805e+07``, which is
    both unreadable and four significant figures of a number the caller may
    well want to quote. Whole numbers stay whole and keep their thousands
    separators; fractions keep enough digits to be worth having.
    """
    if value is None:
        return "n/a"
    number = float(value)
    if number.is_integer() and abs(number) < 1e15:
        return f"{int(number):,}"
    if abs(number) >= 0.001:
        return f"{number:,.4f}".rstrip("0").rstrip(".")
    return f"{number:,.6g}"


def require_user(user):
    """Reject an anonymous caller for a tool that needs an account."""
    if user is None:
        raise AuthenticationRequired(
            "This action needs a signed-in GeoQuery account. Reconnect the "
            "server and complete the GeoQuery sign-in."
        )
    return user


def fmt_count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n:,} {singular if n == 1 else (plural or singular + 's')}"
