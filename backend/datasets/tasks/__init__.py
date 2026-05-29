from celery import shared_task


@shared_task
def build_dataset_docs_task(public_only=True):
    from datasets.tasks.create_docs import build_dataset_docs
    return build_dataset_docs(public_only=public_only)