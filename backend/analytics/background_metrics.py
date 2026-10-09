"""Background pipeline metrics, served by the Celery parent on its own port.

Counters and histograms survive child recycling in prometheus_client's
multiprocess files. Last-success timestamps use max across all children,
including exited ones; they reset when the pod/container restarts.
"""

import os
import time
from functools import wraps

from celery.signals import worker_init

# Creates PROMETHEUS_MULTIPROC_DIR before any metrics open their files.
from analytics.metrics import start_worker_exporter
from prometheus_client import Counter, Gauge, Histogram

JOBS = ("builder", "builder_dispatch", "request_sweep", "task_reaper",
        "request_reaper", "materialize", "boundary_ingest")
JOB_RUNS = Counter("geoquery_background_job_runs", "Finished job invocations", ["job_name", "outcome"])
JOB_SECONDS = Histogram(
    "geoquery_background_job_seconds", "Wall time per finished job invocation", ["job_name"],
    buckets=(1, 5, 15, 30, 60, 300, 900, 1800, 3600, 7200, 14400, 28800, 86400),
)
JOB_LAST_SUCCESS = Gauge(
    "geoquery_background_job_last_success_timestamp_seconds",
    "Last time this job returned normally (not a guarantee every item succeeded)",
    ["job_name"], multiprocess_mode="max",
)
WORK = Counter(
    "geoquery_background_work", "Committed useful work or handled batch failures",
    ["operation"],
)
TASK_FAILURES = Counter(
    "geoquery_extract_task_failures",
    "Extract task failures, by exception class, counted as the error sweep "
    "returns them to pending. Recorded here rather than in the worker because "
    "the sweep is the only path out of the error status, so it sees every "
    "failure exactly once -- and it runs six times an hour over a handful of "
    "rows, where the worker runs thousands of tasks a second.",
    ["exception"],
)
TASKS_EXHAUSTED = Gauge(
    "geoquery_extract_tasks_exhausted",
    "Extract tasks left at the error status having used every retry. These are "
    "never retried again and _check_request_tasks treats them as "
    "finished-but-failed, so a request containing one completes WITHOUT that "
    "column rather than waiting -- a silent partial result. Query across pods "
    "with max(): every background-worker pod exports its own series and only "
    "the one that last ran the sweep is fresh, so a non-zero reading can lag "
    "the count dropping back to zero by a sweep interval.",
    multiprocess_mode="livemostrecent",
)
REQUEST_OUTCOMES = Counter(
    "geoquery_request_outcomes", "Committed request terminal transitions, including retries",
    ["outcome"],
)
REQUEST_SECONDS = Histogram(
    "geoquery_request_completion_seconds", "Submission to committed output completion",
    buckets=(10, 30, 60, 300, 900, 1800, 3600, 7200, 14400, 28800, 86400, 172800, 604800),
)
for job_name in JOBS:
    JOB_LAST_SUCCESS.labels(job_name).set(0)
    for outcome in ("success", "error"):
        JOB_RUNS.labels(job_name, outcome)
for operation in ("tasks_created", "tasks_reclaimed", "tasks_retried",
                  "requests_completed", "builder_batch_errors"):
    WORK.labels(operation)
for outcome in ("completed", "failed"):
    REQUEST_OUTCOMES.labels(outcome)


@worker_init.connect
def start_background_exporter(**kwargs):
    # Deliberately separate from WORKER_METRICS_PORT and django-prometheus:
    # only the Celery parent starts a listener, before prefork children exist.
    start_worker_exporter(int(os.getenv("BACKGROUND_METRICS_PORT", "0")))


def observe_job(job_name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            started = time.monotonic()
            try:
                result = function(*args, **kwargs)
            except BaseException:
                JOB_RUNS.labels(job_name, "error").inc()
                raise
            else:
                JOB_RUNS.labels(job_name, "success").inc()
                JOB_LAST_SUCCESS.labels(job_name).set(time.time())
                return result
            finally:
                JOB_SECONDS.labels(job_name).observe(time.monotonic() - started)
        return wrapped
    return decorate


def record_work(operation, count):
    from django.db import transaction

    transaction.on_commit(lambda: WORK.labels(operation).inc(count))


def record_task_failures(counts_by_exception):
    """Count retried task failures by exception class, once the reset commits.

    Deferred like record_work: the point of the count is that those tasks were
    actually returned to pending, so a rolled-back sweep must not report them.
    """
    from django.db import transaction

    def committed():
        for exception, count in counts_by_exception.items():
            TASK_FAILURES.labels(exception=exception).inc(count)

    transaction.on_commit(committed)


def set_tasks_exhausted(count):
    """Publish the current exhausted-task count.

    Set directly rather than on commit: this is a snapshot of already-committed
    state that the sweep happens to read, not an effect of the sweep's own
    write, and it is correct even when the sweep changes nothing.
    """
    TASKS_EXHAUSTED.set(count)


def record_request_outcome(submitted_at, outcome):
    from django.db import transaction
    from django.utils import timezone

    duration = (
        max(0, (timezone.now() - submitted_at).total_seconds())
        if outcome == "completed" else None
    )

    def committed():
        REQUEST_OUTCOMES.labels(outcome).inc()
        if outcome == "completed":
            REQUEST_SECONDS.observe(duration)
            WORK.labels("requests_completed").inc()

    transaction.on_commit(committed)
