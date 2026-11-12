from celery import shared_task


@shared_task
def update_simplified_geometries_task(fc_id):
    """Recompute one collection's simplified-geometry rows on a worker.

    For callers that shouldn't block on simplification; the ingest commands
    call features.matviews.update_simplified_geometries directly instead so
    the update commits atomically with the ingest itself.
    """
    from features.matviews import update_simplified_geometries
    update_simplified_geometries(fc_id)