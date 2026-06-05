from celery import shared_task


@shared_task
def build_boundary_docs_task(public_only=True):
    from features.tasks.create_docs import build_boundary_docs
    return build_boundary_docs(public_only=public_only)