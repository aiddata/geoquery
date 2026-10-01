"""Test helpers shared across apps."""

from django.db import connections


class _ReplicaAlias:
    """The default connection, answering to the "replica" alias.

    Everything but ``alias`` is delegated, so queries run on the default
    connection inside the test's transaction. ``alias`` has to stay "replica":
    Django compares it against a subquery's ``.using()`` alias and refuses
    the query on a mismatch.
    """

    alias = "replica"

    def __init__(self, default):
        self._default = default

    def __getattr__(self, name):
        return getattr(self._default, name)


class ReplicaReadsTestMixin:
    """Let a ``TestCase`` see its own rows through the "replica" alias.

    Mix in ahead of ``TestCase`` for any test that reaches a
    ``.using("replica")`` read. ``TEST: {"MIRROR": "default"}`` in
    settings.DATABASES points the alias at the test database, but it still
    opens a connection of its own, and ``TestCase`` wraps only non-mirror
    aliases in its per-test transaction. Rows a test creates are uncommitted on
    the default connection, so a separate replica connection reads an empty
    database. Routing the alias through the default connection lets those
    reads see the test's data, as a caught-up standby would.

    ``TransactionTestCase`` commits its data, so a real replica connection
    already sees it; those classes only need "replica" in ``databases``.

    The swap is per class rather than global: ``SimpleTestCase`` disables the
    connection of every alias a test does not list in ``databases``, and a
    global swap would leave that guard nothing of its own to disable.
    """

    databases = {"default", "replica"}

    @classmethod
    def setUpClass(cls):
        replica = connections["replica"]
        cls.addClassCleanup(connections.__setitem__, "replica", replica)
        connections["replica"] = _ReplicaAlias(connections["default"])
        super().setUpClass()
