"""Routing for the read-only replica alias.

The replica is opt-in, not automatic: ``db_for_read`` returns ``None`` (no
opinion, so Django uses ``default``) and individual read-heavy call sites ask
for the standby with ``.using("replica")``. Blanket app-level routing is
deliberately avoided -- Django sends ``select_for_update()`` through
``db_for_read``, so an app-wide rule covering ``analytics`` would push the
queryset in ``analytics/tasks/processing.py`` onto a standby and fail with
"cannot execute SELECT FOR UPDATE in a read-only transaction".

Replication is asynchronous with no bounded lag, so sessions, auth/admin,
django-celery-beat and every read-after-write path must stay on ``default``.
Defaulting to ``None`` here gives that for free.

The router still has to exist even though it routes almost nothing: without
``allow_migrate`` pinned to ``default``, ``migrate`` tries to write to the
replica.
"""


class ReadReplicaRouter:
    def db_for_read(self, model, **hints):
        instance = hints.get("instance")
        if instance is not None and instance._state.db:
            # Related lookups stay on whichever database loaded the parent
            # object, so a .using("replica") queryset does not silently follow
            # a foreign key back to the primary mid-serialization.
            return instance._state.db
        return None

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        # Both aliases are the same logical database, so cross-alias relations
        # are always legal.
        return True

    def allow_migrate(self, db, app_label, **hints):
        return db == "default"
