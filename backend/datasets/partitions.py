"""Per-dataset partition creation for extract_tasks and extract_data.

Migration 0021 LIST-partitioned both tables on dataset_id and created one
partition per Dataset that existed at the time, plus a DEFAULT partition for
each so that a dataset_id without its own partition still has somewhere to
land instead of every insert failing outright. What it did not add -- and
said so in its own comment -- was anything that creates a partition when a
Dataset is created later. This module is that missing piece.

Why it matters that this runs promptly, rather than being left to the DEFAULT
partition:

  * DEFAULT never drains. Per-dataset partitions do: a dataset's tasks are
    built, processed, and then that partition sits idle forever, which is
    what makes a one-off VACUUM on it permanent (see
    ensure_dataset_partitions' sibling maintenance work). Rows parked in
    DEFAULT keep churning as long as *any* unpartitioned dataset is being
    processed, so DEFAULT's status=0 partial index bloats continuously and
    nothing ever cleans it up for good.

  * The claim path prunes on dataset_id (processing.claim_pending_tasks
    passes an explicit `t.dataset_id = ANY(...)`). Rows in DEFAULT cannot be
    pruned to a per-dataset partition, so they are scanned on every claim.

  * It is a ratchet. CREATE TABLE ... PARTITION OF has to prove that no row
    already in DEFAULT belongs in the new partition, and it holds ACCESS
    EXCLUSIVE while doing it. Measured on production: 11.7 ms against an
    empty DEFAULT, 477 ms with 2M rows parked in it, scaling linearly from
    there. Worse, once rows for dataset N are actually in DEFAULT, creating
    partition N stops being possible at all -- Postgres rejects it with
    "updated partition constraint for default partition would be violated by
    some row" and the rows have to be relocated by hand first. Creating the
    partition up front, while DEFAULT is empty, is the cheap moment; every
    moment after that is more expensive than the last.

An empty partition costs essentially nothing, which is why migration 0021
gave one to every dataset including inactive ones rather than creating them
lazily.
"""

import logging

from django.db import OperationalError, connection, transaction

logger = logging.getLogger(__name__)


# The LIST-partitioned parents from migration 0021. Both are keyed on
# dataset_id and both got a DEFAULT partition, so both need a per-dataset
# child for every new Dataset.
#
# Order matters: extract_data holds an FK to extract_tasks, so the referenced
# table's partition is created first. Do not reorder.
PARTITIONED_PARENTS = ("extract_tasks", "extract_data")


# Measured lock footprint of CREATE TABLE extract_tasks_ds_N PARTITION OF
# extract_tasks, rather than assumed:
#
#   extract_tasks          ACCESS EXCLUSIVE
#   extract_tasks_default  ACCESS EXCLUSIVE
#   extract_data           SHARE ROW EXCLUSIVE   (inbound FK from extract_data)
#
# So it stalls both halves of the worker loop at once: ACCESS EXCLUSIVE on
# extract_tasks blocks every claim, and SHARE ROW EXCLUSIVE on extract_data
# conflicts with ROW EXCLUSIVE, which is what every result write takes. The
# reverse holds too -- creating an extract_data partition needs a lock on
# extract_tasks to inherit that same FK -- so the two parents cannot be
# treated as independent, and contention on either blocks both.
#
# Worse than the duration is the queueing: an ACCESS EXCLUSIVE request waits
# ahead of the statements arriving behind it, so sitting on one slow in-flight
# query stalls the whole fleet, not just this statement. A short lock_timeout
# makes the DDL give up rather than form that queue.
#
# Nothing is lost by giving up: the DEFAULT partition already accepts the
# rows, so this is an optimisation to be retried, never a correctness
# requirement. Retries come from
# datasets.tasks.ensure_dataset_partitions_task and the periodic
# ensure-dataset-partitions beat entry.
DEFAULT_LOCK_TIMEOUT = "3s"


def partition_name(parent, dataset_id):
    """Return the per-dataset partition name migration 0021 established."""
    return f"{parent}_ds_{dataset_id}"


def _checked_id(dataset_id):
    """Return dataset_id as an int, rejecting anything unsafe to interpolate.

    The value reaches DDL as part of an identifier (extract_tasks_ds_42) and
    as a partition bound, neither of which can be a bind parameter, so it is
    validated here rather than trusted. bool is rejected explicitly because
    it is an int subclass and would otherwise name a partition
    extract_tasks_ds_True.
    """
    if isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
        raise TypeError(f"dataset_id must be an int, got {dataset_id!r}")
    if dataset_id <= 0:
        raise ValueError(f"dataset_id must be positive, got {dataset_id!r}")
    return dataset_id


def missing_partitions(dataset_id):
    """Return [(parent, child)] for this dataset's partitions that don't exist.

    A catalog lookup, deliberately: it takes no lock on the partitioned
    parents. `CREATE TABLE IF NOT EXISTS` would be shorter but would mean
    reaching for ACCESS EXCLUSIVE on extract_tasks every time something asks
    whether a partition is already there -- and in steady state the answer is
    always yes, for every dataset, on every sweep.
    """
    dataset_id = _checked_id(dataset_id)
    wanted = {partition_name(p, dataset_id): p for p in PARTITIONED_PARENTS}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname FROM pg_class WHERE relname = ANY(%s)",
            [list(wanted)],
        )
        existing = {row[0] for row in cursor.fetchall()}
    return [(parent, child) for child, parent in wanted.items() if child not in existing]


def rows_parked_in_default(dataset_id):
    """Return {parent: row_count} for rows of this dataset sitting in DEFAULT.

    Non-zero means the ratchet already caught this dataset: the partition can
    no longer simply be created, because Postgres will refuse to re-point the
    DEFAULT partition's constraint while rows that belong in the new partition
    are still in it. Those rows have to be moved out first, which is a
    deliberate operation and not something this module does on its own.
    """
    dataset_id = _checked_id(dataset_id)
    counts = {}
    with connection.cursor() as cursor:
        for parent in PARTITIONED_PARENTS:
            cursor.execute(
                f'SELECT count(*) FROM "{parent}_default" WHERE dataset_id = %s',
                [dataset_id],
            )
            counts[parent] = cursor.fetchone()[0]
    return counts


def ensure_dataset_partitions(dataset_id, lock_timeout=DEFAULT_LOCK_TIMEOUT):
    """Create any missing per-dataset partitions. Returns the names created.

    Idempotent and safe to call repeatedly: partitions that already exist are
    skipped without touching the parents at all (see missing_partitions).

    Each partition is created in its own transaction so that giving up on one
    parent does not discard a partition already created on the other -- the
    two are independent, and a half-done call that created extract_tasks_ds_N
    should keep it.

    A lock_timeout expiry is logged and reported back as "not created", not
    raised: DEFAULT accepts the rows meanwhile, so the right response is to
    try again later rather than to fail whatever triggered this.
    """
    dataset_id = _checked_id(dataset_id)
    created = []
    for parent, child in missing_partitions(dataset_id):
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = %s", [lock_timeout])
                    # IF NOT EXISTS covers the race where two callers both saw
                    # the partition missing; the loser gets a notice, not an
                    # error. missing_partitions is what keeps the common case
                    # from reaching this statement at all.
                    cursor.execute(
                        f'CREATE TABLE IF NOT EXISTS "{child}" '
                        f'PARTITION OF "{parent}" FOR VALUES IN ({dataset_id})'
                    )
        except OperationalError as exc:
            # lock_timeout, and anything else transient enough to be worth
            # another attempt. Deliberately not fatal -- see the docstring.
            logger.warning(
                "could not create partition %s yet (%s); DEFAULT is holding "
                "this dataset's rows until a retry succeeds",
                child,
                exc,
            )
            continue
        logger.info("created partition %s", child)
        created.append(child)
    return created


def ensure_all_dataset_partitions(lock_timeout=DEFAULT_LOCK_TIMEOUT):
    """Create missing partitions for every Dataset. Returns (created, blocked).

    The safety net behind the post_save signal, and the backfill path for
    datasets that predate this module. ``blocked`` lists dataset ids whose
    rows are already in DEFAULT, which no amount of retrying will fix -- they
    are surfaced rather than retried silently.
    """
    from datasets.models import Dataset

    created, blocked = [], []
    for dataset_id in Dataset.objects.values_list("id", flat=True).order_by("id"):
        if not missing_partitions(dataset_id):
            continue
        parked = rows_parked_in_default(dataset_id)
        if any(parked.values()):
            logger.error(
                "dataset %s cannot be partitioned: rows already in DEFAULT (%s). "
                "They must be relocated out of the DEFAULT partition first.",
                dataset_id,
                ", ".join(f"{p}={n}" for p, n in parked.items() if n),
            )
            blocked.append(dataset_id)
            continue
        created.extend(ensure_dataset_partitions(dataset_id, lock_timeout=lock_timeout))
    return created, blocked
