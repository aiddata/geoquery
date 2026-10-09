"""Per-partition autovacuum settings for extract_tasks.

Autovacuum vacuums a table once its dead tuples pass
``autovacuum_vacuum_threshold + autovacuum_vacuum_scale_factor * reltuples``.
At the global 0.2 that is ~70M dead tuples on a 350M-row partition, and the
trigger counts dead *heap* tuples while the cost of not vacuuming lands on the
partial indexes. The claim walks ``WHERE status = 0``, and every task leaves
that index on its first update, so the index can be almost entirely dead
entries while the heap is nowhere near the threshold. Measured on production
in October 2026:

* An *active* partition (ds_24, 7,340 dead tuples/s) took 141 minutes between
  vacuums and its pending index grew to 14 GB for ~1.2 GB of live entries. At
  0.05 a vacuum runs every ~35 minutes for ~20 MB/s of vacuum I/O; at 0.01 it
  would have cost ~126 MB/s, because every run scans all of the partition's
  indexes however few tuples it removes.
* A *drained* partition (ds_23: no pending rows, 36M dead tuples against a
  70M threshold) is stuck. Nothing updates it again, so the threshold is never
  reached, yet every claim still walked its 704 MB of dead pending entries --
  277 ms per claim, inside the fleet-wide claim lock, to return zero rows.
  One vacuum takes it to a single buffer, permanently.

So no single setting is right. An active partition wants a moderate trigger;
a drained one wants exactly one more vacuum and then nothing. The default
partition and every partition created later need the same treatment, and
``CREATE TABLE ... PARTITION OF`` does not inherit reloptions. Hence a
reconciler rather than a migration: it puts each partition on the profile its
state calls for, every run, so a new partition, a drained one, and one that
fills up again (new resources or processing options for its dataset) all end
up right without anyone remembering to do it.

extract_data is deliberately left on the global settings: it is written once
per task and deleted only on a rerun, so it has no partial index churning
underneath an unreachable trigger.
"""

import logging

from django.db import OperationalError, connection, transaction
from psycopg import errors, sql

logger = logging.getLogger(__name__)

PARENT = "extract_tasks"

# Each value is applied verbatim as a reloption.
ACTIVE = {"autovacuum_vacuum_scale_factor": "0.05"}
# scale_factor 0 and threshold 0 trigger on any dead tuple. After the one
# vacuum this exists for there are none, so it costs nothing afterwards.
DRAINED = {
    "autovacuum_vacuum_scale_factor": "0",
    "autovacuum_vacuum_threshold": "0",
}
PROFILES = {"active": ACTIVE, "drained": DRAINED}

# Options this module owns: set when a profile asks for them, reset otherwise.
# cost_limit is here only so the hand-set overrides from October 2026 (1000 on
# ds_23 and ds_24) are removed; neither profile sets it, leaving the cost
# balanced across autovacuum workers by the global setting.
MANAGED = (
    "autovacuum_vacuum_scale_factor",
    "autovacuum_vacuum_threshold",
    "autovacuum_vacuum_cost_limit",
)

# ALTER TABLE ... SET (autovacuum_*) takes SHARE UPDATE EXCLUSIVE. That does
# not conflict with claims or result writes (ROW EXCLUSIVE), only with another
# VACUUM, ANALYZE or index build on the partition. An autovacuum in progress
# is cancelled after deadlock_timeout (1s) in our favour, so this only has to
# outlast that; a manual VACUUM or REINDEX is waited out for this long and
# then the partition is left for the next run.
LOCK_TIMEOUT = "3s"

_PARTITIONS_SQL = """
    SELECT c.relname, coalesce(c.reloptions, '{}')
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    WHERE i.inhparent = %s::regclass
    ORDER BY c.relname
"""

# Both checks are served by partial indexes -- the claim index (status = 0)
# and the stale-claims index (status IN (2, 3)) -- so they read a handful of
# pages, except on a partition whose dead entries are exactly what this is
# here to clear, and then only until its vacuum. A partition with tasks still
# running counts as active: their completions would leave dead tuples behind
# the drained profile's one vacuum.
_HAS_WORK_SQL = """
    SELECT EXISTS (SELECT 1 FROM {p} WHERE status = 0)
        OR EXISTS (SELECT 1 FROM {p} WHERE status IN (2, 3))
"""


def _managed(reloptions):
    """The MANAGED subset of a pg_class.reloptions array, as a dict."""
    current = dict(opt.split("=", 1) for opt in reloptions)
    return {k: v for k, v in current.items() if k in MANAGED}


def _alter(partition, wanted):
    """SET the wanted options and RESET the other managed ones."""
    table = sql.Identifier(partition)
    to_set = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.SQL(k), sql.Literal(v))
        for k, v in wanted.items()
    )
    stmts = [sql.SQL("ALTER TABLE {} SET ({})").format(table, to_set)]
    to_reset = [k for k in MANAGED if k not in wanted]
    if to_reset:
        stmts.append(sql.SQL("ALTER TABLE {} RESET ({})").format(
            table, sql.SQL(", ").join(sql.SQL(k) for k in to_reset)
        ))
    return stmts


def reconcile_partition_autovacuum(*, dry_run=False):
    """Put every extract_tasks partition on the profile its state calls for.

    Returns counts -- partitions checked, changed to each profile, already
    right, skipped because the lock was not available -- and under
    "changes" the (partition, profile) pairs changed or, on a dry run,
    that would be.
    """
    result = {"partitions": 0, "active": 0, "drained": 0, "unchanged": 0, "skipped": 0}
    changes = []
    with connection.cursor() as cursor:
        cursor.execute(_PARTITIONS_SQL, [PARENT])
        partitions = cursor.fetchall()

    for partition, reloptions in partitions:
        result["partitions"] += 1
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL(_HAS_WORK_SQL).format(p=sql.Identifier(partition)))
            profile = "active" if cursor.fetchone()[0] else "drained"
        wanted = PROFILES[profile]
        if _managed(reloptions) == wanted:
            result["unchanged"] += 1
            continue
        if dry_run:
            result[profile] += 1
            changes.append((partition, profile))
            continue
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
                for stmt in _alter(partition, wanted):
                    cursor.execute(stmt)
        except OperationalError as exc:
            if not isinstance(exc.__cause__, errors.LockNotAvailable):
                raise
            # A manual VACUUM or REINDEX holds the partition; next run.
            logger.warning("Skipped %s, lock not available: %s", partition, exc)
            result["skipped"] += 1
            continue
        logger.info("Set %s to %s %s", partition, profile, wanted)
        result[profile] += 1
        changes.append((partition, profile))
    return {**result, "changes": changes}
