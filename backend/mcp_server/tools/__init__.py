"""Tool registration.

Each module exposes a ``register(mcp, user_dep)``. ``user_dep`` is the
dependency that resolves the calling user, built once here and shared, so
every tool identifies the caller the same way and no module reaches for the
access token itself.

Tool bodies are also available as plain ``_name(user, ...)`` functions in each
module. That is what makes them testable: a Django ``TestCase`` calls them
directly with a fixture user, and only a handful of integration tests need to
stand a server up.
"""

from __future__ import annotations

from collections.abc import Callable

from fastmcp.dependencies import Depends

from . import catalog, explore, map, requests, resources


def register_all(mcp, user_resolver: Callable[[], object] | None = None) -> None:
    if user_resolver is None:
        from mcp_server.auth import resolve_current_user

        user_resolver = resolve_current_user

    # A single Depends instance shared by every tool: uncalled_for caches a
    # resolved dependency per call keyed on the factory, so the user is looked
    # up once per tool call no matter how many parameters reference it.
    user_dep = Depends(user_resolver)

    for module in (catalog, explore, map, requests, resources):
        module.register(mcp, user_dep)

    from mcp_server import prompts

    prompts.register(mcp)
