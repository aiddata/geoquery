from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Dataset


@receiver(post_save, sender=Dataset)
def on_dataset_created(sender, instance, created, **kwargs):
    """Give a newly created Dataset its extract_tasks/extract_data partitions.

    Only on creation. ingest.py saves a dataset a second time right after
    creating it, to patch in the spatial/temporal fields it derives from the
    filesystem, and update_or_create saves on every re-ingest -- none of which
    needs this to run again. ensure_dataset_partitions is idempotent anyway,
    so the guard is about not queueing pointless work.

    Dispatched to Celery via on_commit rather than run inline, for two
    reasons. The DDL takes ACCESS EXCLUSIVE on extract_tasks and may wait up
    to lock_timeout for it, which is not something to make an admin save or
    an ingest run sit through; and if it does time out it needs somewhere to
    be retried from, which a task has and a signal does not. on_commit means
    the task can never look for a Dataset the transaction has not yet made
    visible.

    Nothing breaks if the task never runs -- the DEFAULT partitions accept
    the rows regardless, and the periodic ensure-dataset-partitions beat
    entry sweeps up anything missed. The partition is what keeps those rows
    prunable and cheap to vacuum, not what makes them storable. See
    datasets.partitions for why it is still worth doing promptly.
    """
    if not created:
        return

    from datasets.tasks import ensure_dataset_partitions_task

    transaction.on_commit(
        lambda: ensure_dataset_partitions_task.delay(instance.id)
    )
