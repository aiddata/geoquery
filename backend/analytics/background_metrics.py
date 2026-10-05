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

JOBS = ("extract_sync", "request_sweep", "task_reaper",
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
for operation in ("tasks_reset", "tasks_reclaimed", "tasks_retried", "tasks_discarded",
                  "requests_completed", "sync_chunks", "sync_published", "sync_errors"):
    WORK.labels(operation)
for outcome in ("completed", "failed"):
    REQUEST_OUTCOMES.labels(outcome)


# Extraction health, refreshed by every sync run (analytics.tasks.maintenance.
# sync_extract_work) from the database, so it keeps reporting while the
# processing fleet is scaled to zero. "mostrecent" because several background
# children may have written a value; only the latest describes the database.
DIRTY_SCOPES = Gauge(
    "geoquery_extract_dirty_scopes",
    "Input scopes (dataset or collection) with changes sync has not published yet",
    ["kind"], multiprocess_mode="mostrecent",
)
ERRORING_SCOPES = Gauge(
    "geoquery_extract_erroring_scopes",
    "Dirty input scopes whose last sync attempt failed (see extract_input_state.last_error)",
    ["kind"], multiprocess_mode="mostrecent",
)
OLDEST_DIRTY_SECONDS = Gauge(
    "geoquery_extract_oldest_dirty_scope_seconds",
    "Time since the least recently touched dirty scope last changed or progressed",
    ["kind"], multiprocess_mode="mostrecent",
)
BOOTSTRAP_PENDING = Gauge(
    "geoquery_extract_bootstrap_pending_datasets",
    "Datasets initialize_extract_work has not finished; nothing processes them",
    multiprocess_mode="mostrecent",
)
LEASES = Gauge(
    "geoquery_extract_leases",
    "Outstanding lease pages: outstanding (all), expired (owner gone, awaiting "
    "takeover), parked (dataset or option inactive)",
    ["state"], multiprocess_mode="mostrecent",
)
OLDEST_LEASE_SECONDS = Gauge(
    "geoquery_extract_oldest_lease_seconds",
    "Age of the oldest outstanding lease page, from its first assignment",
    multiprocess_mode="mostrecent",
)
MAX_LEASE_ATTEMPTS = Gauge(
    "geoquery_extract_lease_max_attempts",
    "Highest assignment count among outstanding leases",
    multiprocess_mode="mostrecent",
)
PAIR_ERRORS = Gauge(
    "geoquery_extract_pair_errors",
    "Current pairs held back by an error (see extract_task_build_progress.last_error)",
    multiprocess_mode="mostrecent",
)
WORK_DEMAND = Gauge(
    "geoquery_extract_work_demand",
    "extract_work_demand(): the autoscaler's estimate of outstanding feature-pair work",
    multiprocess_mode="mostrecent",
)


def update_extract_health():
    from django.db import connection

    from analytics.sync import health
    from analytics.tasks.leases import lease_health

    scopes = health()
    for kind in ("dataset", "collection"):
        values = scopes.get(kind, {})
        DIRTY_SCOPES.labels(kind).set(values.get("dirty", 0))
        ERRORING_SCOPES.labels(kind).set(values.get("erroring", 0))
        OLDEST_DIRTY_SECONDS.labels(kind).set(values.get("oldest_dirty_seconds", 0))
    BOOTSTRAP_PENDING.set(scopes.get("dataset", {}).get("bootstrap_pending", 0))
    leases = lease_health()
    for state in ("outstanding", "expired", "parked"):
        LEASES.labels(state).set(leases[state])
    OLDEST_LEASE_SECONDS.set(leases["oldest_seconds"])
    MAX_LEASE_ATTEMPTS.set(leases["max_attempts"])
    PAIR_ERRORS.set(leases["pair_errors"])
    with connection.cursor() as cursor:
        cursor.execute("SELECT extract_work_demand()")
        WORK_DEMAND.set(cursor.fetchone()[0])


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
