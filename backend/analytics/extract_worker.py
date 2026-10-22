"""The extract worker: runs extraction work claimed straight from Postgres.

Each worker slot loops over one unit of work at a time, in this order:

1. pending task rows -- requests, retries and anything sync reset -- claimed
   in a chunk straight to running (claim_pending_tasks), computed one at a
   time, and persisted together;
2. otherwise, one coverage chunk for a non-global dataset whose watermark is
   behind (analytics.coverage), so lease scans have covered features to find;
3. then one lease page of background work (analytics.tasks.leases), whose
   task rows are only created when it finishes;
4. and, when there was nothing at all, a jittered idle wait.

Nothing is claimed ahead of the slot that will run it, so a
higher-priority request is next in line for whichever slot finishes first,
and a worker that stops can hand back exactly the work it hadn't started.
Reconciling input changes (analytics.sync) runs on the background workers
instead, so a busy processing fleet can never starve it.

This used to be a Celery worker consuming messages that carried already-
claimed task ids. The broker added nothing the table didn't already do, and
fitting the table into its model took a self-chaining task, a beat top-up
and a claimed-but-undelivered status, while prefetch held hundreds of
thousands of claimed tasks out of reach of new work.

Each slot is its own single-process ProcessPoolExecutor. One executor with N
workers would be less code, but when any of its children dies abruptly (an
OOM kill, a segfault in GDAL) the executor marks itself broken and kills
every other child mid-chunk; per-slot executors confine that to the slot.
max_tasks_per_child recycles a slot's process after that many chunks,
reclaiming memory that creeps up per task in rasterio/GDAL, and requires the
spawn start method -- so children run django.setup() themselves, and this
module must stay importable without Django being set up (it is imported to
unpickle run_chunk before the initializer runs).

SIGTERM or SIGINT stops the worker gracefully: each slot finishes the task it
is on, persists the computed portion, releases the rest back to pending,
and exits. A slot computing a lease page finishes it within
EXTRACT_WORKER_DRAIN_SECONDS or gives it back under a new token, refunding
the assignment; a hard kill leaves it to expire. Children
ignore both signals; a Ctrl-C reaches the whole process group, and only the
parent should act on it.
"""

import logging
import multiprocessing
import random
import signal
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool

from analytics import metrics
from analytics.query_tags import tagged

logger = logging.getLogger(__name__)

# The parent's stop event, set in each child by _init_child.
_stop = None
_chunk_starts = None


def _init_child(stop_event, chunk_starts):
    global _stop, _chunk_starts
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    import django

    django.setup()
    _stop = stop_event
    _chunk_starts = chunk_starts


# Consecutive database failures in this process, for the slot's backoff.
_infra_failures = 0


def _infra_backoff_seconds():
    """Exponential, jittered and capped: an outage must not become a storm."""
    delay = min(300.0, 5.0 * 2 ** max(_infra_failures - 1, 0))
    return delay * random.uniform(0.75, 1.25)


@tagged("extract")
def run_chunk(idle_seconds, slot=0):
    """Run one unit of work and return how many task rows it claimed.

    Pending task rows first; with none, one coverage chunk and then one lease
    page. Results and outcomes stay in memory until the unit ends, including
    a graceful stop, and then commit together.

    Every database connection alias is closed after every unit, so a slot
    holds no pooler client connection between them, and a connection the
    pooler dropped is never reused. When there was nothing to do, the slot
    waits about ``idle_seconds``, jittered so slots that went idle together
    don't claim together; after a database failure it backs off
    exponentially instead. The stop event cuts either wait short.
    """
    global _infra_failures
    from django.db import connections

    try:
        claimed, failed = _run_task_chunk(slot)
        worked = bool(claimed)
        if not claimed and not failed and not _stop.is_set():
            try:
                worked = _run_background(slot) or worked
            except Exception:
                logger.exception("Background extraction failed")
                failed = True
    finally:
        connections.close_all()
        if _chunk_starts is not None:
            _chunk_starts[slot] = 0

    if failed:
        _infra_failures += 1
        delay = _infra_backoff_seconds()
        metrics.INFRA_BACKOFF_SECONDS.observe(delay)
        _stop.wait(delay)
    else:
        _infra_failures = 0
        if not worked:
            _stop.wait(idle_seconds * random.uniform(0.75, 1.25))
    return len(claimed)


def _run_task_chunk(slot):
    """Claim one chunk of task rows and run it. Returns ``(claimed, failed)``.

    If persistence fails, unresolved claims are released as well.
    """
    from analytics.tasks import processing

    claimed = []
    outcomes = []
    started = 0
    failed = False
    metrics.batch_started()
    try:
        claimed = processing.claim_pending_tasks(processing._claim_batch_size())
        chunk_started = time.perf_counter()
        if claimed and _chunk_starts is not None:
            _chunk_starts[slot] = time.monotonic()
        for task_id, dataset_id in claimed:
            if _stop.is_set():
                break
            started += 1
            try:
                processing._run_extract_task(task_id, dataset_id, outcomes=outcomes)
            except Exception:
                logger.exception("Extract task %s failed", task_id)
    except Exception:
        logger.exception("Extract chunk failed after %d of %d tasks", started, len(claimed))
        failed = True
    finally:
        try:
            processing._flush_outcomes(outcomes)
        except Exception:
            logger.exception("Could not persist extract chunk outcomes")
            failed = True
        unstarted = claimed if failed else claimed[started:]
        if unstarted:
            try:
                released = processing._release_claimed_tasks(unstarted)
                logger.info("Released %d of %d unresolved tasks", released, len(unstarted))
            except Exception:
                logger.exception("Could not release %d unstarted tasks", len(unstarted))
        metrics.batch_finished()
        if claimed:
            metrics.CHUNK_SECONDS.observe(time.perf_counter() - chunk_started)
        if _chunk_starts is not None:
            _chunk_starts[slot] = 0
    return claimed, failed


def _run_background(slot):
    """One coverage chunk, then one lease page. True if either did anything.

    Raises after a database failure (the lease, if any, already given back)
    so the caller backs off.
    """
    from analytics.coverage import run_coverage_chunk
    from analytics.tasks.leases import claim_lease, run_lease

    covered = run_coverage_chunk() is not None
    if _stop.is_set():
        return covered
    lease = claim_lease()
    if lease is None:
        return covered
    if _chunk_starts is not None:
        _chunk_starts[slot] = time.monotonic()
    run_lease(lease, _stop)
    return True


class ExtractWorker:
    """Keeps ``concurrency`` slots each running one chunk at a time."""

    def __init__(self, concurrency, max_chunks_per_child, idle_seconds, executor_factory=None):
        context = multiprocessing.get_context("spawn")
        self.concurrency = concurrency
        self.idle_seconds = idle_seconds
        self.stop_event = context.Event()
        self.chunk_starts = context.Array("d", concurrency, lock=False)
        self._executor_factory = executor_factory or (
            lambda: ProcessPoolExecutor(
                max_workers=1,
                mp_context=context,
                initializer=_init_child,
                initargs=(self.stop_event, self.chunk_starts),
                max_tasks_per_child=max_chunks_per_child,
            )
        )

    def stop(self, signum=None, frame=None):
        if not self.stop_event.is_set():
            logger.info("Stopping: finishing current tasks and releasing the rest")
            self.stop_event.set()

    def run(self):
        previous = {sig: signal.signal(sig, self.stop) for sig in (signal.SIGTERM, signal.SIGINT)}

        slots = [self._executor_factory() for _ in range(self.concurrency)]
        futures = {}
        try:
            for i in range(self.concurrency):
                futures[self._submit(slots, i)] = i
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    i = futures.pop(future)
                    self.chunk_starts[i] = 0
                    try:
                        future.result()
                    except BrokenProcessPool:
                        self._replace(slots, i)
                    except Exception:
                        logger.exception("Slot %d's chunk raised", i)
                    if not self.stop_event.is_set():
                        futures[self._submit(slots, i)] = i
        finally:
            for slot in slots:
                slot.shutdown(wait=True)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        logger.info("Stopped")

    def _submit(self, slots, i):
        """Start a chunk on slot ``i``, replacing the slot if its process died.

        A child can die after its last chunk returned but before this call --
        killed while idle, say -- and then the executor refuses new work with
        BrokenProcessPool here rather than through a future. A fresh executor
        only starts its process once it has work, so it cannot already be
        broken.
        """
        try:
            return slots[i].submit(run_chunk, self.idle_seconds, i)
        except BrokenProcessPool:
            self._replace(slots, i)
            return slots[i].submit(run_chunk, self.idle_seconds, i)

    def _replace(self, slots, i):
        logger.error("Slot %d's worker process died; replacing it", i)
        metrics.POOL_BREAKS.inc()
        self.chunk_starts[i] = 0
        slots[i].shutdown(wait=False, cancel_futures=True)
        slots[i] = self._executor_factory()
