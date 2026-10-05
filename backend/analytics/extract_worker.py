"""The extract worker: claims chunks of extract tasks from Postgres and runs them.

extract_tasks is the queue. A worker slot loops: claim a chunk of pending
tasks straight to running (claim_pending_tasks), computes them one at a time,
persists their results and statuses together, then claims the next chunk.
Nothing is claimed ahead of the slot that will run it, so a
higher-priority request is next in line for whichever slot finishes first,
and a worker that stops can hand back exactly the tasks it hadn't started.

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
and exits. Children
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


@tagged("extract")
def run_chunk(idle_seconds, slot=0):
    """Claim one chunk, run every task in it, and return how many were claimed.

    Results and outcomes stay in memory until the chunk ends, including a
    graceful stop. They then commit together, before unstarted tasks are
    released. If persistence fails, unresolved claims are released as well.

    The database connection is closed after every chunk, so a slot holds no
    pooler client connection between chunks, and a connection the pooler
    dropped is never reused. When the queue is empty or the chunk failed
    (the database is unreachable, say), the slot waits about ``idle_seconds``
    before its next claim, jittered so slots that went idle together don't
    claim together; the stop event cuts the wait short.
    """
    from django.db import connections

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
        connections.close_all()
        metrics.batch_finished()
        if claimed:
            metrics.CHUNK_SECONDS.observe(time.perf_counter() - chunk_started)
        if _chunk_starts is not None:
            _chunk_starts[slot] = 0

    if failed or not claimed:
        _stop.wait(idle_seconds * random.uniform(0.75, 1.25))
    return len(claimed)


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
