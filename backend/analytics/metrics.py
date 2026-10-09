"""Prometheus metrics for the extract task pipeline.

Throughput, where each task's time goes, and what the fleet spends getting
the next chunk -- the numbers that decide which bottleneck to work on next.
See docs/get-involved/contributing/dev/database.md, Appendix C, for why
these need to be continuous rather than sampled from logs: minute-scale
throughput swings 29k-52k tasks/min, so an effect is only visible when
comparing hours.

The extract worker (analytics.extract_worker) runs tasks in child processes,
each with its own copy of these metrics. They are only scraped when
PROMETHEUS_MULTIPROC_DIR is set in the worker's environment, which switches
prometheus_client to writing values to per-process files that
start_worker_exporter, in the parent, sums. Without it
(dev, tests, the backend) they are ordinary in-process metrics that nothing
exports.
"""

import glob
import os
import time

from prometheus_client import CollectorRegistry, Counter, Histogram, multiprocess, start_http_server

# In multiprocess mode an unlabeled metric opens its file when it is defined,
# below, which fails if the directory does not exist yet.
if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    os.makedirs(os.environ["PROMETHEUS_MULTIPROC_DIR"], exist_ok=True)

# Tasks run ~0.1s median, but phases range from sub-millisecond row locks to
# multi-second raster reads on large features.
_PHASE_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
# The claim lock is shared fleet-wide, so waits run from nothing to minutes
# when every worker starts at once (a rollout, or a scale-up from idle).
_DISPATCH_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
_IDLE_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)
# A chunk is claimed rows held in status 2, which free_stale_processing_tasks
# reclaims after STALE_TASK_MINUTES (30) -- so resolve the approach to that.
_CHUNK_BUCKETS = (1, 5, 10, 30, 60, 120, 300, 600, 900, 1200, 1500, 1800, 2400, 3600)

TASKS = Counter(
    "geoquery_extract_tasks",
    "Extract tasks run, by dataset and outcome. completed = status 1; "
    "failed = status -1; unavailable = the claimed row was no longer running, "
    "or was filtered out; error = an exception before the row was loaded.",
    ["dataset_id", "outcome"],
)

TASK_PHASE_SECONDS = Histogram(
    "geoquery_extract_task_phase_seconds",
    "Wall time one task spent in each phase. lock = fetch the claimed "
    "row's inputs for manual calls; load = resource, geometry and category map "
    "lookups, including amortized batch reads in the chunk worker; extract = "
    "processor calls (raster I/O and compute); write = build rows plus an "
    "amortized share of replacing the batch's results; finalize = amortized "
    "claim recheck and status update, and commit. Time waiting in the result "
    "buffer is excluded.",
    ["phase"],
    buckets=_PHASE_BUCKETS,
)

TASK_PHASE_CPU_SECONDS = Counter(
    "geoquery_extract_task_phase_cpu_seconds",
    "Process CPU time spent in each phase. Divide its rate by the rate of "
    "geoquery_extract_task_phase_seconds_sum for the fraction of a phase "
    "spent computing rather than waiting on the database or disk.",
    ["phase"],
)

DISPATCH_SECONDS = Histogram(
    "geoquery_extract_dispatch_seconds",
    "Time spent claiming the next chunk. lock_wait = acquiring the fleet-wide "
    "claim lock, including any wait for a pooler connection; claim = select "
    "and mark running while holding it, through commit.",
    ["stage"],
    buckets=_DISPATCH_BUCKETS,
)

SLOT_IDLE_SECONDS = Histogram(
    "geoquery_extract_slot_idle_seconds",
    "Time a worker process spent between finishing one chunk and starting "
    "its next one, including any wait for an empty queue to refill.",
    buckets=_IDLE_BUCKETS,
)

CHUNK_SECONDS = Histogram(
    "geoquery_extract_chunk_seconds",
    "Wall time from claiming a chunk of tasks to finishing or releasing all "
    "of them. Its claimed rows sit in status 2 for this long, and are "
    "reclaimed by free_stale_processing_tasks after STALE_TASK_MINUTES.",
    buckets=_CHUNK_BUCKETS,
)

POOL_BREAKS = Counter(
    "geoquery_extract_worker_pool_breaks",
    "Worker processes that died abruptly (OOM kill, segfault) and were "
    "replaced. Their unfinished tasks wait for free_stale_processing_tasks.",
)

FLUSH_RETRIES = Counter(
    "geoquery_extract_flush_retries",
    "Additional persistence attempts after transient connection failures.",
)

FLUSH_FAILURES = Counter(
    "geoquery_extract_flush_failures",
    "Persistence batches that exhausted their connection retries.",
)


class WorkerStateCollector:
    """Read slot state shared with children, including chunks still running.

    A slot has one writer while its future is running. The parent clears it
    once that future resolves, including abrupt process death. No PID labels
    or stale multiprocess gauge files accumulate as children are recycled.
    """

    def __init__(self, starts, stale_seconds):
        self.starts = starts
        self.stale_seconds = stale_seconds

    def collect(self):
        from prometheus_client.core import GaugeMetricFamily

        starts = [value for value in self.starts if value > 0]
        values = (
            ("slots", "Configured extract-worker slots in this pod", len(self.starts)),
            ("active_chunks", "Slots currently holding a chunk", len(starts)),
            ("oldest_active_chunk_seconds", "Age of the oldest unfinished chunk in this pod",
             max(0, time.monotonic() - min(starts)) if starts else 0),
            ("stale_task_seconds", "Configured age at which the reaper can reclaim tasks",
             self.stale_seconds),
        )
        for name, help_text, value in values:
            yield GaugeMetricFamily(f"geoquery_extract_{name}", help_text, value=value)


class TaskTimer:
    """Attributes one task's wall and CPU time to the phase it is in.

    ``enter`` closes the current phase and opens the next, and ``finish``
    closes whichever phase is open, so an early return or exception still
    charges its time to the phase where it happened. A phase entered more
    than once (load interleaves with extract for mapped datasets) is summed
    and observed once per task, so histogram counts stay one per task.
    ``enter(None)`` pauses while results are buffered. Batch persistence is
    apportioned with ``add``; ``finish`` runs only once its outcome is known.
    """

    def __init__(self, dataset_id=None):
        self.dataset_id = dataset_id
        self.outcome = "error"
        self._phase = "lock"
        self._wall = {}
        self._cpu = {}
        self._mark = (time.perf_counter(), time.process_time())

    def enter(self, phase):
        wall, cpu = time.perf_counter(), time.process_time()
        if self._phase is not None:
            self.add(self._phase, wall - self._mark[0], cpu - self._mark[1])
        self._phase = phase
        self._mark = (wall, cpu)

    def add(self, phase, wall, cpu):
        """Add a task's share of batch reads/writes, excluding buffer residence."""
        self._wall[phase] = self._wall.get(phase, 0.0) + wall
        self._cpu[phase] = self._cpu.get(phase, 0.0) + cpu

    def finish(self):
        self.enter(None)
        for phase, seconds in self._wall.items():
            TASK_PHASE_SECONDS.labels(phase).observe(seconds)
            TASK_PHASE_CPU_SECONDS.labels(phase).inc(self._cpu[phase])
        dataset = "unknown" if self.dataset_id is None else str(self.dataset_id)
        TASKS.labels(dataset_id=dataset, outcome=self.outcome).inc()


# Per process, and only meaningful within one: a child recycled by
# --max-chunks-per-child starts with no previous chunk to measure from.
_last_batch_end = None


def batch_started():
    if _last_batch_end is not None:
        SLOT_IDLE_SECONDS.observe(time.monotonic() - _last_batch_end)


def batch_finished():
    global _last_batch_end
    _last_batch_end = time.monotonic()


def start_worker_exporter(port, collectors=()):
    """Serve every worker process's metrics, summed, on ``port``.

    Call once, in the extract worker's parent process, before it starts any
    children. Returns
    whether an exporter was started: it needs both a port and
    PROMETHEUS_MULTIPROC_DIR, and without the directory the children's values
    are invisible to this process anyway.

    Files left by an earlier container in the same pod are removed first.
    The directory is normally an emptyDir, which survives container restarts,
    so a restarted worker would otherwise keep counting from its predecessor's
    totals. This process's own files are kept: it may already have opened
    them (POOL_BREAKS is counted here).
    """
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not port or not directory:
        return False

    os.makedirs(directory, exist_ok=True)
    own = f"_{os.getpid()}.db"
    for path in glob.glob(os.path.join(directory, "*.db")):
        if not path.endswith(own):
            os.remove(path)

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=directory)
    for collector in collectors:
        registry.register(collector)
    start_http_server(port, addr="0.0.0.0", registry=registry)
    return True
