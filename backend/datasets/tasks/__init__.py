from celery import shared_task

from analytics.background_metrics import observe_job
from analytics.query_tags import tagged


@shared_task
@tagged("docs.build")
@observe_job("data_docs")
def build_data_docs_task():
    """Nightly: regenerate the data docs pages into the bundle the docs site
    downloads (datasets.docs.build.build_bundle). Returns the manifest."""
    from datasets.docs.build import build_bundle

    return build_bundle()


@shared_task(bind=True, max_retries=5, default_retry_delay=120)
@tagged("partitions.ensure")
def ensure_dataset_partitions_task(self, dataset_id):
    """Create one dataset's extract_tasks/extract_data partitions.

    Retries rather than giving up, because the thing most likely to stop it
    is a lock_timeout waiting for ACCESS EXCLUSIVE on extract_tasks, and that
    clears on its own. Five attempts two minutes apart covers a busy spell.
    Sync makes the same attempt each run before creating the dataset's pairs,
    and the periodic ensure-dataset-partitions sweep is the last backstop.

    Does not retry when rows are already parked in DEFAULT for this dataset
    -- that is the one failure retrying cannot fix, since Postgres will keep
    refusing to re-point the DEFAULT constraint until those rows are moved.
    The sweep (ensure_all_dataset_partitions) logs it as an error and leaves
    it for a human.
    """
    from datasets.models import Dataset
    from datasets.partitions import (
        ensure_dataset_partitions,
        missing_partitions,
        rows_parked_in_default,
    )

    # The id arrives in a message, so it may outlive the Dataset it names: a
    # retry queued before a rollback or a delete, or a replayed message. A
    # partition is keyed on the id alone and would be created perfectly
    # happily for a dataset that no longer exists, leaving an orphan nothing
    # cleans up. Cheaper to check than to find later.
    if not Dataset.objects.filter(id=dataset_id).exists():
        return []

    created = ensure_dataset_partitions(dataset_id)
    outstanding = missing_partitions(dataset_id)
    if outstanding:
        if any(rows_parked_in_default(dataset_id).values()):
            return created
        raise self.retry()
    return created


@shared_task
@tagged("partitions.sweep")
def ensure_all_dataset_partitions_task():
    """Periodic backstop: partition any Dataset the signal path missed."""
    from datasets.partitions import ensure_all_dataset_partitions

    created, blocked = ensure_all_dataset_partitions()
    return {"created": created, "blocked": blocked}
