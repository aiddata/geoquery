from celery import shared_task

from analytics.query_tags import tagged


@shared_task
def build_dataset_docs_task(public_only=True):
    from datasets.tasks.create_docs import build_dataset_docs
    return build_dataset_docs(public_only=public_only)


@shared_task(bind=True, max_retries=5, default_retry_delay=120)
@tagged("partitions.ensure")
def ensure_dataset_partitions_task(self, dataset_id):
    """Create one dataset's extract_tasks/extract_data partitions.

    Retries rather than giving up, because the thing most likely to stop it
    is a lock_timeout waiting for ACCESS EXCLUSIVE on extract_tasks, and that
    clears on its own. Five attempts two minutes apart covers a busy spell;
    past that the periodic ensure-dataset-partitions sweep is the backstop,
    and the DEFAULT partition is holding the rows throughout either way.

    Does not retry when rows are already parked in DEFAULT for this dataset
    -- that is the one failure retrying cannot fix, since Postgres will keep
    refusing to re-point the DEFAULT constraint until those rows are moved.
    It is logged as an error by ensure_all_dataset_partitions' sibling check
    and left for a human.
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
