"""Prometheus metrics for the extract task pipeline.

Throughput, where each task's time goes, and what the fleet spends getting
the next batch -- the numbers that decide which bottleneck to work on next.
See docs/get-involved/contributing/dev/database.md, Appendix C, for why
these need to be continuous rather than sampled from logs: minute-scale
throughput swings 29k-52k tasks/min, so an effect is only visible when
comparing hours.

Celery's prefork pool runs tasks in child processes, each with its own copy
of these metrics. They are only scraped when PROMETHEUS_MULTIPROC_DIR is set
in the worker's environment, which switches prometheus_client to writing
values to per-process files that start_worker_exporter sums. Without it
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
# during a cold-start top-up.
_DISPATCH_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
_IDLE_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)

TASKS = Counter(
    "geoquery_extract_tasks",
    "Extract tasks run, by dataset and outcome. completed = status 1; "
    "failed = status -1; unavailable = the row was no longer claimable; "
    "error = an exception before the row was locked.",
    ["dataset_id", "outcome"],
)

TASK_PHASE_SECONDS = Histogram(
    "geoquery_extract_task_phase_seconds",
    "Wall time one task spent in each phase. lock = select and mark the row "
    "running; load = resource, geometry and category map lookups; extract = "
    "processor calls (raster I/O and compute); write = build and store "
    "extract_data rows; finalize = the terminal status update.",
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
    "Time spent getting the next batch. lock_wait = acquiring the fleet-wide "
    "claim lock, including any wait for a pooler connection; claim = select "
    "and mark queued while holding it, through commit; publish = sending the "
    "batch to the broker.",
    ["stage"],
    buckets=_DISPATCH_BUCKETS,
)

SLOT_IDLE_SECONDS = Histogram(
    "geoquery_extract_slot_idle_seconds",
    "Time a worker process spent between finishing one run_extract_task "
    "message and starting its next one.",
    buckets=_IDLE_BUCKETS,
)


class TaskTimer:
    """Attributes one task's wall and CPU time to the phase it is in.

    ``enter`` closes the current phase and opens the next, and ``finish``
    closes whichever phase is open, so an early return or exception still
    charges its time to the phase where it happened. A phase entered more
    than once (load interleaves with extract for mapped datasets) is summed
    and observed once per task, so histogram counts stay one per task.
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
        self._wall[self._phase] = self._wall.get(self._phase, 0.0) + wall - self._mark[0]
        self._cpu[self._phase] = self._cpu.get(self._phase, 0.0) + cpu - self._mark[1]
        self._phase = phase
        self._mark = (wall, cpu)

    def finish(self):
        self.enter(None)
        for phase, seconds in self._wall.items():
            TASK_PHASE_SECONDS.labels(phase).observe(seconds)
            TASK_PHASE_CPU_SECONDS.labels(phase).inc(self._cpu[phase])
        dataset = "unknown" if self.dataset_id is None else str(self.dataset_id)
        TASKS.labels(dataset_id=dataset, outcome=self.outcome).inc()


# Per process, and only meaningful within one: a child recycled by
# --max-tasks-per-child starts with no previous batch to measure from.
_last_batch_end = None


def batch_started():
    if _last_batch_end is not None:
        SLOT_IDLE_SECONDS.observe(time.monotonic() - _last_batch_end)


def batch_finished():
    global _last_batch_end
    _last_batch_end = time.monotonic()


def start_worker_exporter(port):
    """Serve every worker process's metrics, summed, on ``port``.

    Call once, in the Celery parent process, before the pool forks. Returns
    whether an exporter was started: it needs both a port and
    PROMETHEUS_MULTIPROC_DIR, and without the directory the children's values
    are invisible to this process anyway.

    Files left by an earlier container in the same pod are removed first.
    The directory is normally an emptyDir, which survives container restarts,
    so a restarted worker would otherwise keep counting from its predecessor's
    totals. This process's own files are kept: under --pool=solo it is the
    one running tasks, and may already have opened them.
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
    start_http_server(port, addr="0.0.0.0", registry=registry)
    return True


def worker_process_exited(pid):
    """Drop a dead child's live-gauge files. Counters and histograms persist."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(pid)
