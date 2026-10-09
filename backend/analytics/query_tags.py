"""Attribute database work to the workload that caused it.

pg_stat_statements records what every statement cost but not who issued it,
so linking a Celery task to its queries has been a manual exercise: grep the
worker logs for a task, match statement shapes in pg_stat_statements by eye,
then read pool metrics separately. Three separate investigations on
2026-10-01/02 each took that path, and the bottleneck moved again within a
day of the last one.

A comment prepended to the SQL closes that loop, because the comment travels
with the statement and lands in pg_stat_statements' query text. The obvious
alternative, application_name, does not survive this deployment: a
session-level SET leaks onto the pooled server connection and into whatever
transaction reuses it next (see docs/.../database.md section 5), SET LOCAL
dies with the transaction, and client_addr resolves to the PgBouncer pod
rather than the workload's.

The cost is cardinality. Every distinct (statement shape x tag) becomes its
own pg_stat_statements entry, and when the table fills Postgres evicts the
least-executed entries first -- exactly the rare, expensive statements worth
keeping. pg_stat_statements.max is 10000 and PGC_POSTMASTER, so raising it
needs a database restart, not a reload. That is why tags are a fixed, small
vocabulary of workload names and MUST NOT carry per-request identifiers.
"""

import logging
import re
from contextlib import contextmanager

from django.db import connections

logger = logging.getLogger(__name__)

# Tags land in pg_stat_statements query text and in any slow-query log, so
# they are constrained to a shape that cannot terminate the comment, inject
# SQL, or smuggle in anything identifying.
_SAFE = re.compile(r"[^a-z0-9_.:-]")
_MAX_TAG = 48


def _sanitize(tag):
    return _SAFE.sub("", str(tag).lower())[:_MAX_TAG]


@contextmanager
def tag_queries(workload, *, using="default"):
    """Prefix every statement issued in this block with ``/* gq:<workload> */``.

    Wraps Django's documented execute_wrapper hook, which applies to the
    current connection for the duration of the block and nests cleanly if an
    inner block sets a different tag.

    Deliberately failure-tolerant: this exists to label work, and a bug in
    labelling must never be able to fail the work. If the tag sanitizes to
    nothing, or anything raises while rewriting the SQL, the original query
    is executed untouched.
    """
    name = _sanitize(workload)
    if not name:
        yield
        return

    prefix = f"/* gq:{name} */ "

    def wrapper(execute, sql, params, many, context):
        try:
            # Only str is rewritten. psycopg can be handed bytes or a
            # Composable, and prepending to those would corrupt them.
            if isinstance(sql, str) and not sql.startswith("/* gq:"):
                sql = prefix + sql
        except Exception:  # pragma: no cover - defensive by intent
            logger.warning("query tagging failed for %s", name, exc_info=True)
        return execute(sql, params, many, context)

    with connections[using].execute_wrapper(wrapper):
        yield


def tagged(workload):
    """Decorator form, for wrapping a Celery task body."""

    def outer(fn):
        from functools import wraps

        @wraps(fn)
        def inner(*args, **kwargs):
            with tag_queries(workload):
                return fn(*args, **kwargs)

        return inner

    return outer
