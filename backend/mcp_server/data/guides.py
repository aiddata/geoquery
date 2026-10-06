"""Long-form instructions the model pulls when it needs them.

``SERVER_INSTRUCTIONS`` has to stay short: it is prepended to every
conversation whether or not it is ever relevant. Some instructions are both
long and only occasionally relevant -- how to lay out an artifact built from
GeoQuery data, say -- and inlining those would cost every conversation the
context of advice most of them never use.

So a guide lives in ``mcp_server/guides/`` as a markdown file, and only its
one-line trigger reaches the instructions. The model reads the body with
``get_guide`` when the trigger fires.

Why a tool rather than a resource, given that the rest of this server's
reference material (``geoquery://citing``, the boundary presets) is served as
resources: the MCP spec makes resources *application-driven* -- the host or
the user decides what to fetch -- while tools are model-controlled. A guide is
chosen by the model, at a moment the host cannot predict, so a resource would
leave "read the style guide before you build a page" unactionable in every
client that does not expose resources to the model. The existing resources are
correctly resources; they are data a user attaches, not instructions a model
obeys.

Adding a guide is dropping a ``.md`` file in that directory. Nothing here or
in ``server.py`` enumerates them, so the index and the tool's argument
description stay accurate on their own.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

from .selection import SelectionError

GUIDES_DIR = Path(__file__).resolve().parent.parent / "guides"

_FRONTMATTER_FENCE = "---"


@dataclass(frozen=True)
class Guide:
    """One guide file: its frontmatter, and the markdown below it."""

    name: str
    title: str
    description: str
    when: str
    body: str

    @property
    def trigger(self) -> str:
        """The single line this guide contributes to SERVER_INSTRUCTIONS."""
        return f"    {self.name} -- read it {self.when}"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Separate a leading ``---`` YAML block from the markdown after it.

    A guide with no frontmatter is not an error: it still works, it just has
    no description or trigger to advertise. Failing instead would mean a
    half-written guide takes the whole server down at startup, since the
    index is built while the server is being constructed.
    """
    if not text.startswith(_FRONTMATTER_FENCE):
        return {}, text

    parts = text.split(_FRONTMATTER_FENCE, 2)
    if len(parts) < 3:
        return {}, text

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, parts[2].lstrip("\n")


def _read(path: Path) -> Guide:
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    name = str(meta.get("name") or path.stem)
    return Guide(
        name=name,
        title=str(meta.get("title") or name),
        description=str(meta.get("description") or ""),
        # The default keeps a guide with no trigger out of the "read it when"
        # phrasing, rather than emitting a dangling sentence.
        when=str(meta.get("when") or "when it is relevant"),
        body=body,
    )


def available_guides() -> list[Guide]:
    """Every guide on disk, by name.

    Read fresh on each call, like the map app's HTML, so editing a guide takes
    effect on the next call in development. There are a handful of files of a
    few KB; caching them would buy nothing and would make the server need a
    restart to pick up an edit.
    """
    if not GUIDES_DIR.is_dir():
        return []
    return sorted(
        (_read(path) for path in GUIDES_DIR.glob("*.md")),
        key=lambda guide: guide.name,
    )


def load_guide(name: str) -> Guide:
    """One guide by name, or a ``SelectionError`` naming the ones that exist.

    Same contract as every other lookup in this server: a model that guesses a
    name is told what it could have asked for instead of being refused.
    """
    guides = available_guides()
    for guide in guides:
        if guide.name == name:
            return guide
    raise SelectionError(
        f"No guide named '{name}'. Available: "
        + (", ".join(g.name for g in guides) or "(none)")
    )


@functools.lru_cache(maxsize=1)
def guides_index() -> str:
    """The GUIDES section of SERVER_INSTRUCTIONS, or "" when there are none.

    Cached because it is read once while the server is built, and because the
    instructions are fixed for the life of the process anyway -- a client is
    given them at initialization and never asks again, so re-reading would not
    reach anyone.
    """
    guides = available_guides()
    if not guides:
        return ""
    lines = [
        "GUIDES. Longer instructions kept out of this prompt because they are "
        "only",
        "sometimes relevant. Read one with get_guide(name) before you start the "
        "work",
        "it covers, not after:",
        *(guide.trigger for guide in guides),
    ]
    return "\n".join(lines)
