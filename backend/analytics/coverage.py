"""Coverage: which features fall inside a non-global dataset's extent.

Each non-global dataset has a watermark (extract_coverage_progress). Every
feat_map row at or below it has a coverage row for its geometry (status 1
inside the extent, 0 outside), unless its collection was dirty and holds a
durable rewind below it. Lease scans of that dataset stop at the watermark,
so a feature is only leased once it is known to be covered. Global datasets
cover everything and have no watermark.

Processing worker slots advance watermarks one chunk at a time, between
pending tasks and lease pages (analytics.extract_worker). That replaces the
old pipeline of status -1 placeholder rows, per-dataset Celery checks and a
chord into the builder: there are no placeholders now, only answers.

Invalidation arrives through extract_input_state like every other change: an
extent or global/non-global change resets the dataset's coverage and rewinds
its watermark to 0. A geometry change deletes that geometry's coverage in the
same transaction (the features capture trigger) and rewinds every watermark
below the features that use it. See analytics.sync.
"""

import logging
import time

from django.conf import settings
from django.db import connection, transaction

from analytics import metrics
from analytics.changes import UNAVAILABLE_SQL, lock_states

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 2 * 60 * 1000
LOCK_TIMEOUT_MS = 2 * 1000

_CANDIDATES_SQL = f"""
    SELECT p.dataset_id
    FROM extract_coverage_progress p
    JOIN datasets d ON d.id = p.dataset_id AND d.active AND NOT d.is_global
    JOIN extract_input_state s
      ON s.kind = 'dataset' AND s.object_id = p.dataset_id AND NOT {UNAVAILABLE_SQL}
    WHERE p.covered_up_to_fm_id < extract_eligible_max_fm_id()
    ORDER BY p.covered_up_to_fm_id, p.dataset_id
    LIMIT 8
"""

_WINDOW_SQL = """
    SELECT fm.id, fm.fc_id, fm.geom_id, fc.is_user_upload
    FROM feat_map fm
    JOIN feature_collections fc ON fc.id = fm.fc_id
    WHERE fm.id > %s
    ORDER BY fm.id
    LIMIT %s
"""

_COLLECTION_STATES_SQL = f"""
    SELECT object_id, epoch, {UNAVAILABLE_SQL}, rewind_from
    FROM extract_input_state
    WHERE kind = 'collection' AND object_id = ANY(%s::int[])
    ORDER BY object_id
    FOR SHARE SKIP LOCKED
"""

_INSERT_COVERAGE_SQL = """
    INSERT INTO coverage (geom_id, dataset_id, status)
    SELECT g.id, d.id,
           CASE WHEN ST_Contains(d.spatial_extent, g.shape) THEN 1 ELSE 0 END
    FROM features g
    CROSS JOIN (SELECT id, spatial_extent FROM datasets WHERE id = %s) AS d
    WHERE g.id = ANY(%s::int[])
    ON CONFLICT (geom_id, dataset_id) DO NOTHING
"""


def valid_coverage(using="default"):
    """Coverage rows a reader may serve: status 1, and not being invalidated.

    A dataset whose extent changed, or a collection invalidated with
    invalidate_extract_inputs, keeps its old rows until sync has deleted them
    chunk by chunk. Readers must not answer from those rows in the meantime.
    The exclusion is part of the reader's own statement, so a reset committing
    between two queries cannot let old rows through.
    """
    from django.db.models import Exists, OuterRef

    from analytics.models import Coverage, ExtractInputState
    from features.models import FeatMap

    resetting = ExtractInputState.objects.using(using).filter(reset_coverage=True)
    return (
        Coverage.objects.using(using)
        .filter(status=1)
        .exclude(Exists(resetting.filter(kind="dataset", object_id=OuterRef("dataset_id"))))
        .exclude(Exists(
            FeatMap.objects.using(using).filter(
                geom_id=OuterRef("geom_id"),
                fc_id__in=resetting.filter(kind="collection").values("object_id"),
            )
        ))
    )


def run_coverage_chunk():
    """Advance one dataset's coverage by one chunk.

    Returns the number of feat_map rows examined, or None if no dataset could
    be advanced (none behind, or every candidate busy or dirty).
    """
    with connection.cursor() as cursor:
        cursor.execute(_CANDIDATES_SQL)
        candidates = [r[0] for r in cursor.fetchall()]
    for dataset_id in candidates:
        started = time.perf_counter()
        examined = _cover_chunk(dataset_id)
        if examined is not None:
            metrics.COVERAGE_CHUNKS.labels("advanced").inc()
            metrics.COVERAGE_FEATURES.inc(examined)
            metrics.COVERAGE_CHUNK_SECONDS.observe(time.perf_counter() - started)
            return examined
    if candidates:
        metrics.COVERAGE_CHUNKS.labels("busy").inc()
    return None


def barrier_for(window, states):
    """Lowest feature id a scan may not pass, or None.

    ``window`` is ``[(fm_id, fc_id), ...]`` in id order; ``states`` maps the
    collections that could be share-locked to ``(epoch, unavailable,
    rewind_from)``. A collection being reset as a whole may be skipped above
    its durable rewind, because publishing it brings the scan back. Anything
    else in such a collection, or in a collection held by a writer (absent
    from ``states``), stops the scan just before it. A collection with only
    additive changes pending is scanned like any other.
    """
    for fm_id, fc_id in window:
        state = states.get(fc_id)
        if state is None:
            return fm_id
        _, unavailable, rewind_from = state
        if unavailable and (rewind_from is None or fm_id <= rewind_from):
            return fm_id
    return None


def _cover_chunk(dataset_id):
    limit = settings.EXTRACT_COVERAGE_CHUNK_SIZE
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SET LOCAL statement_timeout = %s; SET LOCAL lock_timeout = %s",
                [STATEMENT_TIMEOUT_MS, LOCK_TIMEOUT_MS],
            )
            guard = lock_states([dataset_id], [], cursor=cursor)
            if not guard.all_clean:
                return None
            # The watermark first, then the window. A collection publish locks
            # every watermark before rewinding, so one this transaction cannot
            # see yet waits for our commit and then rewinds what we leave; one
            # already committed is visible to the window read below. Collection
            # states are taken SKIP LOCKED after it, so that publish (which
            # holds its collection) never deadlocks us.
            cursor.execute(
                """
                SELECT covered_up_to_fm_id FROM extract_coverage_progress
                WHERE dataset_id = %s FOR UPDATE SKIP LOCKED
                """,
                [dataset_id],
            )
            locked = cursor.fetchone()
            if locked is None:
                return None
            watermark = locked[0]

            cursor.execute(_WINDOW_SQL, [watermark, limit])
            rows = cursor.fetchall()
            if not rows:
                return None

            collections = sorted({fc_id for _, fc_id, _, _ in rows})
            cursor.execute(_COLLECTION_STATES_SQL, [collections])
            states = {object_id: tuple(rest) for object_id, *rest in cursor.fetchall()}
            barrier = barrier_for([(fm_id, fc_id) for fm_id, fc_id, _, _ in rows], states)

            eligible = sorted({
                geom_id
                for fm_id, fc_id, geom_id, is_upload in rows
                if (barrier is None or fm_id < barrier)
                and not is_upload
                and not states[fc_id][1]
            })
            if eligible:
                cursor.execute(_INSERT_COVERAGE_SQL, [dataset_id, eligible])

            # Only as far as what was examined. Features committed later with a
            # lower id are caught by their insert's collection rewind.
            new_watermark = rows[-1][0] if barrier is None else barrier - 1
            if new_watermark <= watermark:
                return None
            cursor.execute(
                "UPDATE extract_coverage_progress SET covered_up_to_fm_id = %s WHERE dataset_id = %s",
                [new_watermark, dataset_id],
            )
            logger.debug(
                "Coverage for dataset %s advanced %s -> %s (%d geometries tested)",
                dataset_id, watermark, new_watermark, len(eligible),
            )
            return len(rows)
