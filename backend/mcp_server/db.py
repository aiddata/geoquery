"""Database lifecycle for tools running outside Django's request cycle.

Django closes finished connections in a ``request_finished`` receiver. A
FastMCP process never sends that signal -- there is no Django request -- so
nothing would ever reap the connection a tool opened. That matters more here
than it looks: ``CONN_MAX_AGE`` is 0 (pgBouncer owns the pool, see
``geoquery.settings``), which makes every connection single-use by design, and
FastMCP runs sync tools in a thread pool whose threads are *reused*. Without
this, each pool thread would hold one idle Postgres connection open for the
lifetime of the process, and a connection broken between calls would surface
as an ``InterfaceError`` on the next tool that happened to land on that
thread.

``close_old_connections`` on both sides is what Django itself does around a
request: closing on the way in discards anything stale left by a previous
call, closing on the way out releases the connection this call opened.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connections


def _release_idle_connections() -> None:
    """``close_old_connections()``, minus any connection inside a transaction.

    Django's version drops a connection whose autocommit no longer matches the
    configured value, on the assumption that an atomic block still open at the
    end of a request means something went wrong. That assumption does not hold
    here: a caller may legitimately wrap a tool call in a transaction -- Django's
    own ``TestCase`` does exactly that -- and closing the connection out from
    under it discards uncommitted work and breaks every later query on it.
    Skipping those leaves nothing leaked: whoever opened the transaction owns
    the connection and will close it.
    """
    for connection in connections.all(initialized_only=True):
        if connection.in_atomic_block:
            continue
        connection.close_if_unusable_or_obsolete()


@contextmanager
def django_db() -> Iterator[None]:
    """Give the enclosed work a clean, promptly-released database connection.

    Must be entered **inside the thread that runs the queries**, which is why
    it is a context manager used by ``tools.common.tool_body`` and by the
    resource bodies, and deliberately *not* a ``Depends()`` dependency.

    A dependency looks like the natural fit and silently does not work:
    FastMCP resolves dependencies on an ``AsyncExitStack``, so the teardown
    half runs on the event loop, while the tool body itself ran in a worker
    thread. Django's connections are per-thread, so the event loop would close
    its own (usually none) and leave the worker's open -- one leaked Postgres
    connection per tool call, accumulating until the server cannot connect.
    """
    _release_idle_connections()
    try:
        yield
    finally:
        _release_idle_connections()
