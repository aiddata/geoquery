"""Block extraction: compute many extract tasks per claim, then write them in
one transaction.

The per-task path (analytics.tasks.processing) pays its database cost per
task: a builder INSERT, three status UPDATEs that can never be HOT, and three
commits -- and its raster cost per task too, opening the raster and reading
the feature's window once per processing option. At ~700 tasks/s the fleet
was queueing on the database, not on CPU.

A block is one (resource_ids) unit -- a single resource, or every resource of
one grouped bucket -- crossed with up to EXTRACT_BLOCK_SIZE feat_map rows and
every active processing option of that resource:

  claim    lease the resource's progress pairs (extract_task_build_progress)
           and take the next range of feat_map ids above their watermark
  scan     one partition-pruned query for which of those tasks are already
           done or in flight; only the rest are computed
  load     geometries for the remaining features, in one query
  extract  rasterstats once per resource and option group, over every
           geometry at once -- one raster open, one windowed read per feature
           for all stats (see processors.zonal_stats_rasterstats)
  write    one transaction: write the extract_tasks rows directly as
           complete (or -1) and insert their extract_data, then fence on the
           lease and advance the watermark

So there is no builder and no pending backlog for global datasets, and the
database sees a few statements per block instead of per task.

The per-task path keeps everything else: user requests, non-global
(coverage-gated) datasets, and retries of tasks a block marked -1. The two
can run over the same rows concurrently; see _TAKE_OVER_TASKS_SQL for how
each skips what the other has taken.
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from warnings import catch_warnings

import shapely
from django.conf import settings
from django.db import connection, transaction

from analytics import metrics

logger = logging.getLogger(__name__)

# The write transaction carries the whole block, so it is allowed far longer
# than the builder's 5,000-row batches, but still bounded so a stalled write
# cannot hold a pooler connection indefinitely.
WRITE_STATEMENT_TIMEOUT_MS = 10 * 60 * 1000

_MAX_FEAT_MAP_ID_SQL = "SELECT COALESCE(MAX(id), 0) FROM feat_map"

# Block claims run one at a time. A claim is two statements -- lock a seed
# pair, then lock its siblings -- and SKIP LOCKED alone does not make the pair
# of them atomic: a second claimer arriving in between skips the locked seed,
# seeds on the same resource's next option and leases that by itself, so the
# resource is split into two blocks that each open the raster for part of its
# options. Under the lock the second claimer sees the first one's committed
# lease and moves on to the next resource.
#
# Cheap here, unlike the per-task claim this pattern is borrowed from
# (processing.CLAIM_LOCK_ID): a few millisecond statements on a table of a
# few thousand rows, once per block rather than once per task. Transaction
# scoped, so it is safe under transaction pooling.
#
# Distinct from CLAIM_LOCK_ID (8419307742201) and accounts.adopt_auth_user's
# ADVISORY_LOCK_ID (8419307742115).
BLOCK_CLAIM_LOCK_ID = 8419307742202

_CLAIMABLE = (
    "(p.block_claimed_at IS NULL"
    " OR p.block_claimed_at < NOW() - make_interval(mins => %(lease_minutes)s))"
)

# The joins and filters match the builder's _NEXT_PROGRESS_PAIRS_SQL:
# resource_ids[1] stands in for the pair's dataset, since every resource in a
# grouped bucket belongs to the same one.
#
# Other claimers are kept out by BLOCK_CLAIM_LOCK_ID, not by the row locks.
# FOR UPDATE SKIP LOCKED is for the rows' other writers -- the builder's batch
# and a block's fence both update them -- which the claim steps past rather
# than waiting on while it holds the claim lock.
_SEED_SQL = f"""
    SELECT p.id, p.resource_ids, COALESCE(p.computed_up_to_fm_id, 0),
           d.id, d.task_group_period
    FROM extract_task_build_progress p
    INNER JOIN dataset_resources dr ON dr.id = p.resource_ids[1]
    INNER JOIN processing_options po ON po.id = p.po_id AND po.dataset_id = dr.dataset_id
    INNER JOIN datasets d ON d.id = dr.dataset_id AND d.is_global = TRUE AND d.active = TRUE
    WHERE po.active = TRUE
      AND COALESCE(p.computed_up_to_fm_id, 0) < %(max_fm_id)s
      AND {_CLAIMABLE}
      AND (cardinality(%(datasets)s::integer[]) = 0
           OR d.id = ANY(%(datasets)s::integer[]))
    ORDER BY p.id
    LIMIT 1
    FOR UPDATE OF p SKIP LOCKED
"""

# Every claimable pair of the seed's resource at the same watermark -- usually
# all of its processing options, so the raster is read once for all of them.
# A processing option added later starts at a lower watermark and so forms
# its own group until it catches up. Includes the seed itself, which this
# transaction already holds.
#
# A sibling whose row the builder holds at this instant is still skipped, and
# forms its own block afterwards. That costs one extra raster read, never
# correctness, and waiting for it here would hold the claim lock on a batch
# that can run for minutes.
_SIBLINGS_SQL = f"""
    SELECT p.id, po.id, po.function, po.short_name, po.kwargs::text
    FROM extract_task_build_progress p
    INNER JOIN processing_options po
        ON po.id = p.po_id AND po.active = TRUE AND po.dataset_id = %(dataset_id)s
    WHERE p.resource_ids = %(resource_ids)s::integer[]
      AND COALESCE(p.computed_up_to_fm_id, 0) = %(lo)s
      AND {_CLAIMABLE}
    ORDER BY p.id
    FOR UPDATE OF p SKIP LOCKED
"""

_LEASE_SQL = """
    UPDATE extract_task_build_progress
    SET block_claimed_at = NOW(), block_claim_token = %s
    WHERE id = ANY(%s)
"""

# Run by refresh_lease. Also how a failed block backs off: run_block refreshes
# the lease instead of releasing it, so the block is retried once the lease
# expires rather than immediately by the next chain.
_HEARTBEAT_SQL = """
    UPDATE extract_task_build_progress
    SET block_claimed_at = NOW()
    WHERE id = ANY(%s) AND block_claim_token = %s
"""

# Bounded above by the max feat_map id read before the claim, so the
# watermark never passes a row this block did not see.
_RANGE_SQL = """
    SELECT fm.id, fm.geom_id
    FROM feat_map fm
    INNER JOIN feature_collections fc ON fc.id = fm.fc_id
    WHERE fc.active = TRUE
      AND fc.is_user_upload = FALSE
      AND fm.id > %s AND fm.id <= %s
    ORDER BY fm.id
    LIMIT %s
"""

# Served by extract_tasks_fm_po_resources_null_kwargs_idx, pruned to one
# partition. Status 1 is done; 2 and 3 belong to the per-task path right now.
# Rows at 0 or -1 are recomputed here and taken over by the write.
_SCAN_SQL = """
    SELECT fm_id, po_id, status
    FROM extract_tasks
    WHERE dataset_id = %(dataset_id)s
      AND kwargs IS NULL
      AND resource_ids_hash = extract_tasks_resource_ids_hash(%(resource_ids)s::integer[])
      AND resource_ids = %(resource_ids)s::integer[]
      AND po_id = ANY(%(po_ids)s)
      AND fm_id > %(lo)s AND fm_id <= %(hi)s
"""

_GEOMETRIES_SQL = "SELECT id, ST_AsBinary(shape) FROM features WHERE id = ANY(%s)"

# Advances the watermark and releases the lease in the same transaction as the
# writes below, fenced on the token: if the lease expired and another worker
# took the block over, this matches fewer rows than the block holds and the
# whole transaction rolls back.
#
# It runs LAST, after every extract_tasks write, so a block locks rows in the
# same order as the builder's _INSERT_GLOBAL_BATCH_SQL: extract_tasks first,
# then the progress row. Run first, the two deadlock when both reach the same
# pair -- the block's insert waits on a row the builder has inserted but not
# committed, while the builder's watermark update waits on the progress row
# the block's fence holds. The cost is that a block whose lease was taken over
# does its writes before finding out, which only happens after a takeover.
_COMPLETE_SQL = """
    UPDATE extract_task_build_progress
    SET computed_up_to_fm_id = GREATEST(COALESCE(computed_up_to_fm_id, 0), %s),
        block_claimed_at = NULL,
        block_claim_token = NULL
    WHERE id = ANY(%s) AND block_claim_token = %s
"""

# Scoped to the write transaction, which is what makes temp tables safe under
# transaction pooling: nothing outlives the transaction on the pooled
# connection.
_STAGING_SQL = (
    """CREATE TEMP TABLE block_tasks (
        fm_id integer, po_id integer, status integer, error text
    ) ON COMMIT DROP""",
    """CREATE TEMP TABLE block_data (
        fm_id integer, po_id integer, name text,
        int_value bigint, float_value double precision, str_value text,
        int_values bigint[], float_values double precision[], str_values text[]
    ) ON COMMIT DROP""",
    """CREATE TEMP TABLE block_written (
        id integer, fm_id integer, po_id integer, status integer, taken_over boolean
    ) ON COMMIT DROP""",
)

_DATA_COLUMNS = (
    "int_value", "float_value", "str_value",
    "int_values", "float_values", "str_values",
)
_DATA_TYPES = ["int4", "int4", "text", "int8", "float8", "text", "int8[]", "float8[]", "text[]"]

# One block task's existing row, matched on the unique index
# extract_tasks_fm_po_resources_null_kwargs_idx and pruned to one partition.
_SAME_TASK = """
    t.dataset_id = %(dataset_id)s
    AND t.kwargs IS NULL
    AND t.resource_ids_hash = extract_tasks_resource_ids_hash(%(resource_ids)s::integer[])
    AND t.resource_ids = %(resource_ids)s::integer[]
    AND t.fm_id = s.fm_id AND t.po_id = s.po_id
"""

# Rows are written directly in their final state rather than passing through
# pending, queued and running, so they never enter the partial claim index
# (WHERE status = 0) and are never rewritten. complete_time is required: the
# stats completion chart counts only rows that have one.
#
# Existing rows are taken over in place, and only at status 0 (built but not
# claimed) or -1 (failed). One the per-task path has claimed since the scan
# (2 or 3) fails the WHERE and keeps its own result. SKIP LOCKED steps past a
# row a per-task claim (or a block whose lease was taken over) is holding
# rather than waiting on it; such a row is left to the per-task path, which
# takes 0 directly and -1 once manage_processing_task_errors resets it. The
# per-task claim is SKIP LOCKED too, so neither side ever waits on the other.
#
# A separate UPDATE rather than INSERT ... ON CONFLICT DO UPDATE, for two
# reasons. An upsert draws an id from extract_tasks' 32-bit identity for every
# row it takes over, and throws it away. And RETURNING cannot tell an upsert's
# inserts from its updates -- xmax is unavailable from a partitioned table --
# while this marks exactly the rows it took over, under their row locks, which
# is what _DELETE_REPLACED_DATA_SQL needs.
_TAKE_OVER_TASKS_SQL = f"""
    WITH targets AS MATERIALIZED (
        SELECT t.id, s.fm_id, s.po_id, s.status, s.error
        FROM block_tasks s
        INNER JOIN extract_tasks t ON {_SAME_TASK}
        WHERE t.status IN (0, -1)
        ORDER BY s.fm_id, s.po_id
        FOR UPDATE OF t SKIP LOCKED
    ),
    updated AS (
        UPDATE extract_tasks t
        SET status = targets.status,
            update_time = NOW(),
            complete_time = CASE WHEN targets.status = 1 THEN NOW() END,
            error = targets.error
        FROM targets
        WHERE t.dataset_id = %(dataset_id)s AND t.id = targets.id
        RETURNING t.id, targets.fm_id, targets.po_id, targets.status
    )
    INSERT INTO block_written SELECT id, fm_id, po_id, status, TRUE FROM updated
"""

# Every task with no row yet. Rows that exist -- taken over above, or skipped
# by it -- are filtered out first, so an id is drawn only for a row that is
# actually inserted, or one that loses a race: ON CONFLICT DO NOTHING covers a
# row another transaction commits after this statement's snapshot (the
# builder, or a request creating its tasks), which keeps its own result.
_INSERT_TASKS_SQL = f"""
    WITH inserted AS (
        INSERT INTO extract_tasks
            (dataset_id, resource_ids, task_group_period, fm_id, po_id, status,
             priority, attempts, submit_time, update_time, complete_time, error)
        SELECT %(dataset_id)s, %(resource_ids)s::integer[], %(task_group_period)s,
               s.fm_id, s.po_id, s.status, 0, 0, NOW(), NOW(),
               CASE WHEN s.status = 1 THEN NOW() END, s.error
        FROM block_tasks s
        WHERE NOT EXISTS (SELECT 1 FROM extract_tasks t WHERE {_SAME_TASK})
        ORDER BY s.fm_id, s.po_id
        ON CONFLICT (dataset_id, fm_id, po_id, resource_ids_hash) WHERE kwargs IS NULL
        DO NOTHING
        RETURNING id, fm_id, po_id, status
    )
    INSERT INTO block_written SELECT id, fm_id, po_id, status, FALSE FROM inserted
"""

# Replaces a taken-over task's previous rows wholesale, as the per-task path
# does -- but, as there, only when this run produced rows to replace them
# with, so a total failure keeps whatever an earlier run left. A task this
# block inserted has no rows to replace.
_DELETE_REPLACED_DATA_SQL = """
    DELETE FROM extract_data ed
    USING block_written w
    WHERE ed.dataset_id = %s
      AND ed.extract_task_id = w.id
      AND w.taken_over
      AND EXISTS (
          SELECT 1 FROM block_data b WHERE b.fm_id = w.fm_id AND b.po_id = w.po_id
      )
"""

_INSERT_DATA_SQL = f"""
    INSERT INTO extract_data (dataset_id, extract_task_id, name, {", ".join(_DATA_COLUMNS)})
    SELECT %s, w.id, b.name, {", ".join(f"b.{c}" for c in _DATA_COLUMNS)}
    FROM block_data b
    INNER JOIN block_written w ON w.fm_id = b.fm_id AND w.po_id = b.po_id
"""

_WRITTEN_COUNTS_SQL = "SELECT status, count(*) FROM block_written GROUP BY status"


class LeaseLost(Exception):
    """Another worker owns this block now; nothing this one computed is kept."""


class ResourceUnreadable(Exception):
    """A block's resource cannot be opened, so its failures say nothing about
    the features; the block errors instead of writing them."""

    def __init__(self, resource_id, path, cause):
        self.resource_id = resource_id
        super().__init__(f"resource {resource_id} at {path}: {cause!r}")


@dataclass(frozen=True)
class Option:
    """One processing option, with the kwargs its processor is called with --
    built exactly as the per-task path builds them (see options_for)."""

    po_id: int
    function: str
    op_kwargs: dict


@dataclass
class Block:
    token: uuid.UUID
    pair_ids: list
    dataset_id: int
    resource_ids: list
    task_group_period: str | None
    options: list  # (po_id, function, short_name, po_kwargs)
    lo: int
    hi: int
    features: list  # (fm_id, geom_id)


def _block_size():
    return max(1, getattr(settings, "EXTRACT_BLOCK_SIZE", 2000))


def _lease_minutes():
    return max(1, getattr(settings, "EXTRACT_BLOCK_LEASE_MINUTES", 10))


def claim_block(block_size=None):
    """Lease the next block, or return None when there is nothing to do."""
    block_size = block_size or _block_size()
    params = {
        "lease_minutes": _lease_minutes(),
        "datasets": list(getattr(settings, "EXTRACT_BLOCK_DATASETS", [])),
    }
    with connection.cursor() as cursor:
        cursor.execute(_MAX_FEAT_MAP_ID_SQL)
        max_fm_id = cursor.fetchone()[0]

    token = uuid.uuid4()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [BLOCK_CLAIM_LOCK_ID])
            cursor.execute(_SEED_SQL, {**params, "max_fm_id": max_fm_id})
            seed = cursor.fetchone()
            if seed is None:
                return None
            _seed_id, resource_ids, lo, dataset_id, task_group_period = seed
            cursor.execute(_SIBLINGS_SQL, {
                **params,
                "dataset_id": dataset_id,
                "resource_ids": resource_ids,
                "lo": lo,
            })
            pairs = cursor.fetchall()
            pair_ids = [p[0] for p in pairs]
            cursor.execute(_LEASE_SQL, [token, pair_ids])

    with connection.cursor() as cursor:
        cursor.execute(_RANGE_SQL, [lo, max_fm_id, block_size])
        features = cursor.fetchall()
    # A short page means the range reaches the end of feat_map as of the
    # claim -- including when every remaining row belongs to an inactive or
    # user-uploaded collection, which the builder treats the same way.
    hi = features[-1][0] if len(features) == block_size else max_fm_id

    return Block(
        token=token,
        pair_ids=pair_ids,
        dataset_id=dataset_id,
        resource_ids=list(resource_ids),
        task_group_period=task_group_period,
        options=[
            (po_id, function, short_name, json.loads(kwargs) if kwargs else None)
            for _, po_id, function, short_name, kwargs in pairs
        ],
        lo=lo,
        hi=hi,
        features=features,
    )


def refresh_lease(block):
    """Start the block's lease period again. Fenced on the token, so it never
    touches a lease someone else holds; False means the block was taken over."""
    with connection.cursor() as cursor:
        cursor.execute(_HEARTBEAT_SQL, [block.pair_ids, block.token])
        return cursor.rowcount == len(block.pair_ids)


def back_off_block(block):
    """Hold a failed block's lease for another full lease period, so it is
    retried then rather than straight away.

    Releasing it instead made a deterministic failure fatal to the fleet: the
    released block is the lowest claimable pair, so the next chain to claim
    took it, failed the same way and ended, and so on through every chain.
    """
    refresh_lease(block)


class _LeaseHeartbeat:
    """Keep a block's lease fresh through computation and the write transaction.

    The same design as manage_user_requests._ClaimHeartbeat: without it the
    lease length would be a limit on how long a block may take rather than a
    liveness check, and a slow block would be taken over and recomputed
    forever. Each beat is fenced on the token, so a failed fence means the
    block has been taken over; ``lost`` lets the caller stop early.

    A beat after the write commits can find the token released. The caller
    checks ``lost`` before writing; the write's final fence is authoritative
    thereafter. Stop/join only after the transaction exits, so a beat waiting
    on its final progress-row lock cannot deadlock the commit.
    """

    def __init__(self, block, interval=None):
        self.block = block
        self.interval = _lease_minutes() * 60 / 5 if interval is None else interval
        self.lost = False
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval)
        return False

    def _run(self):
        try:
            while not self._stop.wait(self.interval):
                if not self._beat():
                    return
        finally:
            # This thread has its own connection; leaving it open leaks one
            # per block.
            connection.close()

    def _beat(self):
        try:
            held = refresh_lease(self.block)
        except Exception as e:
            # A transient error must not abandon a block that is otherwise
            # fine; the lease is five beats wide.
            logger.warning("Block lease heartbeat failed: %s", e)
            # Django keeps handing out a connection the server has dropped
            # until something closes it -- which is normally the end of the
            # task, and this thread outlives none. Unclosed, every later beat
            # fails on it too and the lease expires under a live block.
            try:
                connection.close()
            except Exception:
                pass
            return True
        if not held:
            # Also normal after a successful commit releases the token.
            # run_block reports actual loss when its pre-write check or the
            # transaction's final fence fails.
            self.lost = True
            return False
        return True


def options_for(options, category_map=None):
    """Processor kwargs per option, built in the same order as the per-task
    path's op_kwargs: name, then the option's kwargs, then the category map
    for mapped datasets. Global tasks never carry task kwargs."""
    built = []
    for po_id, function, short_name, po_kwargs in options:
        op_kwargs = {"name": short_name}
        if po_kwargs:
            op_kwargs.update(po_kwargs)
        if category_map is not None:
            op_kwargs["category_map"] = category_map
        built.append(Option(po_id=po_id, function=function, op_kwargs=op_kwargs))
    return built


def _groups(options):
    """Partition options into processor calls.

    Stat functions whose kwargs match (apart from name) share one batched
    call; categorical options get one batched call each; anything without a
    batch form (the GeoPackage vector processors) runs one feature at a time.
    """
    from analytics.processors.zonal_stats_rasterstats import BATCH_STATS

    groups = {}
    for option in options:
        if option.function in BATCH_STATS:
            rest = sorted(
                ((k, v) for k, v in option.op_kwargs.items() if k != "name"),
                key=lambda kv: kv[0],
            )
            groups.setdefault(("stats", repr(rest)), []).append(option)
        elif option.function == "rasterstats_default_categorical":
            groups[("categorical", option.po_id)] = [option]
        else:
            groups[("single", option.po_id)] = [option]
    return [(key[0], opts) for key, opts in groups.items()]


def _call(kind, opts, geoms, path):
    """Run one group over ``geoms``. Returns one {po_id: [(name, value)]} per
    geometry, in order."""
    from analytics.processors.zonal_stats_rasterstats import (
        BATCH_STATS,
        rasterstats_batch,
        rasterstats_batch_categorical,
    )
    from analytics.tasks.processing import get_func

    if kind == "stats":
        kwargs = {k: v for k, v in opts[0].op_kwargs.items() if k != "name"}
        stats = [BATCH_STATS[o.function] for o in opts]
        rows = rasterstats_batch(geoms, path, stats, **kwargs)
        return [
            {o.po_id: [(o.op_kwargs["name"], row[BATCH_STATS[o.function]])] for o in opts}
            for row in rows
        ]
    (option,) = opts
    if kind == "categorical":
        outputs = rasterstats_batch_categorical(geoms, path, **option.op_kwargs)
        return [{option.po_id: output} for output in outputs]
    func = get_func(option.function)
    return [{option.po_id: func(geom, path, **option.op_kwargs)} for geom in geoms]


def _call_logged(kind, opts, geoms, path):
    with catch_warnings(record=True) as warnings:
        results = _call(kind, opts, geoms, path)
    for message in sorted({str(w.message) for w in warnings}):
        logger.warning("Warning from %s on %s: %s", [o.function for o in opts], path, message)
    return results


def _check_readable(kind, resource_id, path, cause):
    """Raise ResourceUnreadable if ``path`` cannot be opened at all.

    Called on a resource's first failure, to tell an outage from a bad
    geometry. The share of features that failed cannot: blocks recompute rows
    at -1, so a block whose only needed tasks are deterministic failures
    fails every one of them with the raster perfectly readable.
    """
    try:
        if kind == "single":
            with open(path, "rb") as f:
                f.read(1)
        else:
            # The open rasterstats itself performs.
            import rasterio

            rasterio.open(path).close()
    except Exception as exc:
        raise ResourceUnreadable(resource_id, path, exc) from cause


def compute(geometries, resources, options, should_stop=lambda: False):
    """Run every option over every geometry, for every resource position.

    ``geometries`` maps geom_id -> shapely geometry; ``resources`` is
    [(resource_id, path)] in resource_ids order. Returns ``(produced,
    failures)``, keyed by (geom_id, po_id): produced maps name -> {position:
    value}, as the per-task path accumulates it, and failures lists
    (resource_id, position, exception) for each position that raised.

    A batched call that raises is retried one geometry at a time, so one bad
    geometry fails only its own tasks -- once the resource is known to be
    readable. Its first failure opens the resource itself, and one that will
    not open raises ResourceUnreadable: recorded as failures instead, an
    outage would write the whole range as -1 and advance the watermark past
    it. A file that disappears after that check still fails the rest of this
    block's features; the next block's check catches it.

    ``should_stop`` is checked between calls so a block whose lease was lost
    stops early.
    """
    if not geometries:
        # An already-done range: nothing to open a raster for.
        return {}, {}
    geom_ids = list(geometries)
    geoms = [geometries[g] for g in geom_ids]
    produced = {}
    failures = {}

    def record(geom_id, result, position):
        for po_id, pairs in result.items():
            target = produced.setdefault((geom_id, po_id), {})
            for name, value in pairs:
                target.setdefault(name, {})[position] = value

    for position, (resource_id, path) in enumerate(resources):
        readable = False  # shown by _check_readable, on the first failure
        for kind, opts in _groups(options):
            if should_stop():
                return produced, failures
            try:
                results = _call_logged(kind, opts, geoms, path) if kind != "single" else None
            except Exception as exc:
                if not readable:
                    _check_readable(kind, resource_id, path, exc)
                    readable = True
                logger.warning(
                    "Batched %s on resource %s failed (%r); retrying per feature",
                    [o.function for o in opts], resource_id, exc,
                )
                results = None
            if results is not None:
                for geom_id, result in zip(geom_ids, results):
                    record(geom_id, result, position)
                continue
            for geom_id, geom in zip(geom_ids, geoms):
                try:
                    (result,) = _call_logged(kind, opts, [geom], path)
                except Exception as exc:
                    if not readable:
                        _check_readable(kind, resource_id, path, exc)
                        readable = True
                    for o in opts:
                        failures.setdefault((geom_id, o.po_id), []).append(
                            (resource_id, position, exc)
                        )
                    continue
                record(geom_id, result, position)
    return produced, failures


def scan_block(block):
    """Which of the block's tasks to compute: (fm_id, geom_id, po_id) for
    every task not already done or in flight. Rows found at 0 or -1 are
    included; the write takes them over in place."""
    with connection.cursor() as cursor:
        cursor.execute(_SCAN_SQL, {
            "dataset_id": block.dataset_id,
            "resource_ids": block.resource_ids,
            "po_ids": [o[0] for o in block.options],
            "lo": block.lo,
            "hi": block.hi,
        })
        scanned = cursor.fetchall()
    taken = {(fm_id, po_id) for fm_id, po_id, status in scanned if status in (1, 2, 3)}
    return [
        (fm_id, geom_id, po_id)
        for fm_id, geom_id in block.features
        for po_id, *_ in block.options
        if (fm_id, po_id) not in taken
    ]


def load_inputs(block, geom_ids):
    from datasets.models import Dataset, DatasetResource

    dataset = Dataset.objects.get(id=block.dataset_id)
    by_id = {
        r.id: r for r in DatasetResource.objects.filter(id__in=block.resource_ids)
    }
    resources = [
        (rid, Path(dataset.path) / by_id[rid].path) for rid in block.resource_ids
    ]
    category_map = (
        dict(dataset.mappings.values_list("map_val", "map_name")) if dataset.mapped else None
    )
    with connection.cursor() as cursor:
        cursor.execute(_GEOMETRIES_SQL, [list(geom_ids)])
        geometries = {gid: shapely.from_wkb(bytes(wkb)) for gid, wkb in cursor.fetchall()}
    return geometries, resources, options_for(block.options, category_map)


def _data_fields():
    """ExtractData's model fields for ``name`` and each value column."""
    from analytics.models import ExtractData

    return {
        column: ExtractData._meta.get_field(column) for column in ("name", *_DATA_COLUMNS)
    }


def _length_limits(fields):
    """The varchar lengths of ExtractData's text columns, from the model."""
    return {
        "name": fields["name"].max_length,
        "str_value": fields["str_value"].max_length,
        "str_values": fields["str_values"].base_field.max_length,
    }


def _overflow(name, field, value, limits):
    """The ExtractData column one row would overflow, or None."""
    if len(name) > limits["name"]:
        return "name"
    if field == "str_value" and len(value) > limits["str_value"]:
        return "str_value"
    if field == "str_values" and any(
        v is not None and len(v) > limits["str_values"] for v in value
    ):
        return "str_values"
    return None


def _check_integer_range(field, value):
    """Validate bigint bounds after field coercion, before staging in COPY.

    Django's BigIntegerField prepares Python ints without checking their
    range. Leaving that check to PostgreSQL aborts the entire block instead
    of failing just the task that produced the out-of-range value.
    """
    if field not in ("int_value", "int_values"):
        return
    lower, upper = connection.ops.integer_field_range("BigIntegerField")
    values = value if field == "int_values" else [value]
    if any(v is not None and not lower <= v <= upper for v in values):
        raise OverflowError(f"value out of range for extract_data.{field}")


def _check_text(name, field, value):
    """PostgreSQL text cannot contain NUL, including text array elements."""
    values = [("name", name)]
    if field == "str_value":
        values.append((field, value))
    elif field == "str_values":
        values.extend((field, v) for v in value)
    for column, text in values:
        if text is not None and "\x00" in text:
            raise ValueError(f"NUL byte in extract_data.{column}")


def task_rows(block, needed, produced, failures):
    """The rows to stage for each needed (fm_id, geom_id, po_id).

    Each value goes through its ExtractData field's get_db_prep_value, which
    is what the per-task path's bulk_create runs it through, so a name whose
    positions disagree on type is stored exactly as that path stores it (a
    float in an int array truncated, an int in a float array widened) rather
    than handed to COPY, which rejects it.

    A task with a value its column cannot take -- one the field cannot
    coerce, an integer outside bigint bounds, text containing NUL, or one
    too long -- is failed
    here, with no data rows. Numeric conversion can also raise OverflowError
    (for example int(inf) in a mixed array). Left in, these would fail the
    whole block; the per-task path fails only that task (bulk_create raises,
    the task goes to -1 and keeps any earlier rows), and this matches it.
    """
    from analytics.tasks.processing import data_values

    n = len(block.resource_ids)
    fields = _data_fields()
    limits = _length_limits(fields)
    tasks, data = [], []
    for fm_id, geom_id, po_id in needed:
        label = f"block fm={fm_id} po={po_id}"
        rows, overflow, invalid = [], None, None
        for name, field, value in data_values(produced.get((geom_id, po_id), {}), n, label):
            try:
                if field is not None:
                    value = fields[field].get_db_prep_value(value, connection)
                    _check_integer_range(field, value)
                _check_text(name, field, value)
            except (TypeError, ValueError, OverflowError) as exc:
                invalid = invalid or exc
                continue
            overflow = overflow or _overflow(name, field, value, limits)
            row = [fm_id, po_id, name] + [None] * len(_DATA_COLUMNS)
            if field is not None:
                row[3 + _DATA_COLUMNS.index(field)] = value
            rows.append(row)

        failed = failures.get((geom_id, po_id))
        if invalid:
            logger.warning("Task %s: a value cannot be stored: %r", label, invalid)
            status, error, rows = -1, repr(invalid)[:100], []
        elif overflow:
            logger.warning("Task %s: a value is too long for extract_data.%s", label, overflow)
            status, error, rows = -1, f"value too long for extract_data.{overflow}", []
        elif failed:
            error = "; ".join(f"resource {rid}[{i}]: {exc!r}" for rid, i, exc in failed)[:100]
            status = -1
        else:
            status, error = 1, None
        tasks.append((fm_id, po_id, status, error))
        data.extend(rows)
    return tasks, data


def write_block(block, tasks, data):
    """Commit a block: task rows, their data and the watermark, all or nothing.

    Raises LeaseLost (rolling everything back) if the lease is no longer
    this worker's. Returns the count of rows written per status.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", [WRITE_STATEMENT_TIMEOUT_MS])
            counts = _write_tasks(cursor, block, tasks, data) if tasks else {}
            # Last: see _COMPLETE_SQL for the lock order this keeps.
            cursor.execute(_COMPLETE_SQL, [block.hi, block.pair_ids, block.token])
            if cursor.rowcount < len(block.pair_ids):
                raise LeaseLost(block.pair_ids)
            return counts


def _write_tasks(cursor, block, tasks, data):
    for statement in _STAGING_SQL:
        cursor.execute(statement)
    # COPY rather than INSERT: a block can stage tens of thousands of rows,
    # and this is one round trip for all of them.
    with cursor.cursor.copy("COPY block_tasks (fm_id, po_id, status, error) FROM STDIN") as copy:
        copy.set_types(["int4", "int4", "int4", "text"])
        for row in tasks:
            copy.write_row(row)
    with cursor.cursor.copy(
        f"COPY block_data (fm_id, po_id, name, {', '.join(_DATA_COLUMNS)}) FROM STDIN"
    ) as copy:
        copy.set_types(_DATA_TYPES)
        for row in data:
            copy.write_row(row)

    params = {
        "dataset_id": block.dataset_id,
        "resource_ids": block.resource_ids,
        "task_group_period": block.task_group_period,
    }
    cursor.execute(_TAKE_OVER_TASKS_SQL, params)
    cursor.execute(_INSERT_TASKS_SQL, params)
    cursor.execute(_DELETE_REPLACED_DATA_SQL, [block.dataset_id])
    cursor.execute(_INSERT_DATA_SQL, [block.dataset_id])
    cursor.execute(_WRITTEN_COUNTS_SQL)
    return dict(cursor.fetchall())


def run_block(block_size=None):
    """Claim, compute and write one block.

    Returns a summary, or None when there was nothing to claim -- which is
    what ends a run_extract_block chain. A block that raises after its claim
    is logged, backed off for a lease period (see back_off_block) and
    reported as an error result, so the chain moves on to other work. Only a
    failure to claim propagates.
    """
    phase_started = time.perf_counter()

    def phase(name):
        nonlocal phase_started
        now = time.perf_counter()
        metrics.BLOCK_PHASE_SECONDS.labels(name).observe(now - phase_started)
        phase_started = now

    block = claim_block(block_size)
    if block is None:
        return None
    phase("claim")

    dataset_label = str(block.dataset_id)
    try:
        needed = scan_block(block)
        skipped = len(block.features) * len(block.options) - len(needed)
        phase("scan")

        with _LeaseHeartbeat(block) as heartbeat:
            geom_ids = {geom_id for _, geom_id, _ in needed}
            geometries, resources, options = load_inputs(block, geom_ids)
            # A feat_map row whose geometry is gone has nothing to compute;
            # the per-task claim would not find it either.
            missing = sum(n[1] not in geometries for n in needed)
            needed = [n for n in needed if n[1] in geometries]
            phase("load")
            produced, failures = compute(
                geometries, resources, options, should_stop=lambda: heartbeat.lost
            )
            phase("extract")
            metrics.BLOCK_FEATURES.observe(len(geometries))
            if heartbeat.lost:
                raise LeaseLost(block.pair_ids)

            tasks, data = task_rows(block, needed, produced, failures)
            if not refresh_lease(block):
                raise LeaseLost(block.pair_ids)
            counts = write_block(block, tasks, data)
            phase("write")
    except LeaseLost:
        logger.warning(
            "Block on resources %s fm (%s, %s] lost its lease; discarded",
            block.resource_ids, block.lo, block.hi,
        )
        metrics.BLOCKS.labels("lost").inc()
        return {"lost": True}
    except Exception as exc:
        logger.exception(
            "Block dataset=%s pairs=%s resources=%s fm (%s, %s] failed; "
            "retrying after the lease expires",
            block.dataset_id, block.pair_ids, block.resource_ids, block.lo, block.hi,
        )
        if isinstance(exc, ResourceUnreadable):
            metrics.BLOCK_RESOURCE_ERRORS.labels(
                dataset_id=dataset_label, resource_id=str(exc.resource_id)
            ).inc()
        try:
            back_off_block(block)
        except Exception:
            # The lease still expires on its own, just sooner.
            logger.exception("Could not back off block on pairs %s", block.pair_ids)
        metrics.BLOCKS.labels("error").inc()
        return {"error": True, "resource_ids": block.resource_ids, "lo": block.lo}

    metrics.BLOCKS.labels("written").inc()

    completed, failed = counts.get(1, 0), counts.get(-1, 0)
    unavailable = missing + len(needed) - completed - failed
    for outcome, count in (
        ("completed", completed), ("failed", failed),
        ("unavailable", unavailable), ("skipped", skipped),
    ):
        if count:
            metrics.TASKS.labels(dataset_id=dataset_label, outcome=outcome).inc(count)
    logger.info(
        "Block dataset=%s resources=%s fm (%s, %s]: %d features, %d options, "
        "%d completed, %d failed, %d unavailable, %d already done",
        block.dataset_id, block.resource_ids, block.lo, block.hi,
        len(block.features), len(block.options), completed, failed, unavailable, skipped,
    )
    return {
        "dataset_id": block.dataset_id,
        "resource_ids": block.resource_ids,
        "lo": block.lo,
        "hi": block.hi,
        "completed": completed,
        "failed": failed,
        "unavailable": unavailable,
        "skipped": skipped,
    }
