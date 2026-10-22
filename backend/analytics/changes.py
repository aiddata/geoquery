"""Input change capture and the guards that fence extraction work against it.

Changes to anything an extraction reads -- a dataset's path, a resource, a
processing option, a category map, a collection's eligibility, a feature's
shape -- are recorded by database triggers (migration 0031) in
extract_input_state, in the same transaction as the change. Each dataset and
each collection has one row: a scope. A scope is dirty while its generation
differs from applied_generation; analytics.sync reconciles it and publishes
the new generation. This module is the Python side of that contract.

Two counters. generation advances on every change and drives sync. epoch
advances only on an invalidation, a change that makes stored results or
in-flight work wrong; work fences on epoch, so an additive change (a new
feature, resource or option) never discards finished work. Targeted
invalidations name what they cover in extract_invalid_items; a scope being
reset as a whole (reset_tasks or reset_coverage) or still bootstrapping is
unavailable, and no work starts on it.

Fencing. Work takes FOR SHARE on the available states it depends on, in short
transactions, and records their epochs. A trigger or sync needs an exclusive
lock on the same rows, so it cannot change a scope while work holds the
share, and work that later finds a different epoch, or an unavailable scope,
knows its inputs changed underneath it. FOR KEY SHARE would not do: it does
not conflict with the triggers' non-key UPDATE. Shares are taken with SKIP
LOCKED, never by waiting: a long ingest transaction can hold a state's row
lock for minutes, and a worker queued behind it would hold everything it had
already locked.

A guard protects only what is read after it. Discover candidates without
locking, take the guards, then reread every input whose scope the guard is
meant to cover (metadata, collection membership) and retry if the set of
scopes changed. Readers check validity in the same statement as the results
they return (the extract_valid_tasks view), never in a separate query.

Lock order, everywhere:

    dataset states by id
    collection states by id
    coverage progress by dataset
    pairs by id
    leases by id
    tasks by (dataset_id, id)

The task path's advisory claim lock comes before all of them; sync never
takes it. A lease claim or coverage chunk takes its pair or watermark right
after its dataset share and then the collection states, all SKIP LOCKED, so
it never waits holding them. No lock is held across computation.

A missing state is an initialization error, never "clean".
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from django.db import connection, transaction

logger = logging.getLogger(__name__)

DATASET = "dataset"
COLLECTION = "collection"


class InputStateMissing(RuntimeError):
    """A dataset or collection has no extract_input_state row.

    Rows are created by triggers when the dataset or collection is created,
    and by migration 0031 for everything older. A missing one means
    initialization did not run; work on that scope must not proceed as if it
    were clean.
    """


@dataclass
class Generations:
    """Input epochs a piece of work was computed against.

    (Named for the generations it once held; it holds each scope's epoch.)
    """

    datasets: dict[int, int] = field(default_factory=dict)
    collections: dict[int, int] = field(default_factory=dict)

    def as_json(self):
        return {
            "datasets": {str(k): v for k, v in sorted(self.datasets.items())},
            "collections": {str(k): v for k, v in sorted(self.collections.items())},
        }

    @classmethod
    def from_json(cls, value):
        value = value or {}
        return cls(
            datasets={int(k): v for k, v in (value.get("datasets") or {}).items()},
            collections={int(k): v for k, v in (value.get("collections") or {}).items()},
        )


@dataclass
class GuardResult:
    """What a guard acquisition found.

    ``clean`` holds the epochs of every scope that is now share-locked and
    available. ``unavailable`` names the scopes that are being reset as a
    whole, bootstrap-pending, or locked by a writer: work on them is
    deferred, not failed.
    """

    clean: Generations
    unavailable_datasets: set[int]
    unavailable_collections: set[int]

    @property
    def all_clean(self):
        return not self.unavailable_datasets and not self.unavailable_collections


# A scope no work may start on: being reset as a whole, or not yet
# initialized. Targeted invalidations leave a scope available; the tasks they
# name are excluded by extract_valid_tasks instead.
UNAVAILABLE_SQL = "(reset_tasks OR reset_coverage OR bootstrap_pending)"

_LOCK_STATES_SQL = f"""
    SELECT kind, object_id, epoch, {UNAVAILABLE_SQL}
    FROM extract_input_state
    WHERE (kind = 'dataset' AND object_id = ANY(%s::int[]))
       OR (kind = 'collection' AND object_id = ANY(%s::int[]))
    ORDER BY kind = 'collection', object_id
    FOR SHARE SKIP LOCKED
"""

_EXISTING_STATES_SQL = """
    SELECT kind, object_id FROM extract_input_state
    WHERE (kind = 'dataset' AND object_id = ANY(%s::int[]))
       OR (kind = 'collection' AND object_id = ANY(%s::int[]))
"""


def _missing_states(cursor, dataset_ids, collection_ids, returned):
    cursor.execute(_EXISTING_STATES_SQL, [dataset_ids, collection_ids])
    existing = set(cursor.fetchall())
    wanted = {(DATASET, i) for i in dataset_ids} | {(COLLECTION, i) for i in collection_ids}
    return wanted - existing - returned


def lock_states(dataset_ids, collection_ids, *, cursor=None, prefix=""):
    """Share-lock the given scopes, in lock order, and report which are available.

    Must run inside a transaction: the shares last until it ends. Rows another
    transaction holds exclusively are skipped, not waited for, and reported
    unavailable along with scopes being reset or bootstrapped. Raises
    InputStateMissing if a scope has no state at all.

    ``prefix`` rides in the same execute (the task path's SET LOCAL
    synchronous_commit), so a guard that opens a transaction can carry it.
    """
    assert connection.in_atomic_block, "input guards are only held inside a transaction"
    dataset_ids = sorted({int(i) for i in dataset_ids})
    collection_ids = sorted({int(i) for i in collection_ids})
    result = GuardResult(Generations(), set(), set())
    if not dataset_ids and not collection_ids:
        return result

    from analytics import metrics

    own_cursor = cursor is None
    cursor = cursor or connection.cursor()
    try:
        started = time.perf_counter()
        cursor.execute(prefix + _LOCK_STATES_SQL, [dataset_ids, collection_ids])
        if prefix:
            cursor.nextset()
        rows = cursor.fetchall()
        metrics.GUARD_SECONDS.labels("wait").observe(time.perf_counter() - started)
        returned = {(kind, object_id) for kind, object_id, *_ in rows}
        if len(returned) < len(dataset_ids) + len(collection_ids):
            missing = _missing_states(cursor, dataset_ids, collection_ids, returned)
            if missing:
                raise InputStateMissing(
                    "No extract_input_state for " + ", ".join(f"{k} {i}" for k, i in sorted(missing))
                )
            locked = {(DATASET, i) for i in dataset_ids} | {(COLLECTION, i) for i in collection_ids}
            for kind, object_id in locked - returned:
                _unavailable(result, kind, object_id)
    finally:
        if own_cursor:
            cursor.close()

    for kind, object_id, epoch, unavailable in rows:
        if unavailable:
            _unavailable(result, kind, object_id)
        elif kind == DATASET:
            result.clean.datasets[object_id] = epoch
        else:
            result.clean.collections[object_id] = epoch
    return result


def _unavailable(result, kind, object_id):
    if kind == DATASET:
        result.unavailable_datasets.add(object_id)
    else:
        result.unavailable_collections.add(object_id)


def recheck(expected: Generations, *, cursor=None):
    """Share-lock the scopes ``expected`` names; True if each is available and unchanged.

    The completion check every path runs before it writes results: a lease
    page, a task chunk, or a request's output. Locks are held until the
    caller's transaction ends.
    """
    guard = lock_states(expected.datasets, expected.collections, cursor=cursor)
    return (
        guard.all_clean
        and guard.clean.datasets == expected.datasets
        and guard.clean.collections == expected.collections
    )


_READ_STATES_SQL = f"""
    SELECT kind, object_id, epoch, {UNAVAILABLE_SQL}
    FROM extract_input_state
    WHERE (kind = 'dataset' AND object_id = ANY(%s::int[]))
       OR (kind = 'collection' AND object_id = ANY(%s::int[]))
"""


@dataclass(frozen=True)
class StateSnapshot:
    epoch: int
    unavailable: bool


def read_states(dataset_ids=(), collection_ids=(), *, using="default"):
    """Unlocked snapshot of scope states, for discovery. Missing scopes are absent.

    Never decide to write on this alone: take the guards and recheck.
    """
    from django.db import connections

    dataset_ids = sorted({int(i) for i in dataset_ids})
    collection_ids = sorted({int(i) for i in collection_ids})
    if not dataset_ids and not collection_ids:
        return {}
    with connections[using].cursor() as cursor:
        cursor.execute(_READ_STATES_SQL, [dataset_ids, collection_ids])
        return {
            (kind, object_id): StateSnapshot(*rest)
            for kind, object_id, *rest in cursor.fetchall()
        }


def jsonb(value):
    """Decode a jsonb column fetched through a raw cursor.

    Django registers psycopg's plain text loader for jsonb, so raw cursors
    return the JSON text, not the decoded value (see visualize.data).
    """
    import json

    return json.loads(value) if isinstance(value, str) else value


def mark(kind, ids, *, rewind_from=None, sync_pairs=False, reset_tasks=False,
         reset_coverage=False, invalidate=False, items=None):
    """Record a durable change to the given scopes, as the triggers do.

    ``items`` is ``(item_kind, item_ids)`` for a targeted reset of one scope
    (see analytics.models.ExtractInvalidItem); it implies ``invalidate``.

    For repair and import workflows that changed inputs out of band (see the
    invalidate_extract_inputs and rewind_pair_cursors commands). It cannot make
    a concurrent in-place file rewrite safe, or detect one: files must be
    published at a new path (see database.md).
    """
    ids = sorted({int(i) for i in ids})
    if not ids:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT extract_input_mark(%s, %s::int[], %s::int[], %s, %s, %s, %s)",
            [kind, ids, [rewind_from] * len(ids), sync_pairs, reset_tasks, reset_coverage,
             invalidate or items is not None],
        )
        if items is not None:
            (scope,) = ids
            item_kind, item_ids = items
            item_ids = sorted({int(i) for i in item_ids})
            cursor.execute(
                "SELECT extract_input_items(%s, %s::int[], %s, %s::int[])",
                [kind, [scope] * len(item_ids), item_kind, item_ids],
            )
    wake_sync()


# The ORM side of extract_valid_tasks (migration 0031): a semi-join on the
# view's primary key columns, inside the reader's own statement.
_VALID_TASK_SQL = (
    "EXISTS (SELECT 1 FROM extract_valid_tasks v "
    'WHERE v.dataset_id = "extract_tasks"."dataset_id" AND v.id = "extract_tasks"."id")'
)


def only_valid(tasks):
    """Narrow an ExtractTask queryset to tasks whose stored state may be trusted.

    Excludes datasets being reset as a whole or bootstrapping and the tasks a
    pending targeted reset names, in the same statement as the caller's read,
    so a reset committing in between cannot slip stale values through.
    """
    return tasks.extra(where=[_VALID_TASK_SQL])


def _send_wake():
    from analytics.tasks.maintenance import sync_extract_work

    try:
        # No publish retries: if the broker is down, beat's next tick is the
        # fallback, and an ingest must not stall waiting on it.
        sync_extract_work.apply_async(retry=False)
    except Exception:
        # Beat runs sync every EXTRACT_SYNC_INTERVAL_SECONDS regardless; a
        # lost notification only costs latency.
        logger.warning("Could not wake extract sync", exc_info=True)


def wake_sync():
    """Ask a background worker to reconcile soon, once the transaction commits.

    At most once per transaction however many changes it makes, so an ingest
    of a million features sends one message. The changes themselves are
    already durable in extract_input_state; this only shortens the wait for
    the next beat tick.
    """
    conn = transaction.get_connection()
    if conn.in_atomic_block and any(func is _send_wake for _, func, *_ in conn.run_on_commit):
        return
    transaction.on_commit(_send_wake)
