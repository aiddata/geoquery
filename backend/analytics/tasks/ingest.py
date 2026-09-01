import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from analytics.ingest import ingest_custom_boundary
from analytics.models import Request

logger = logging.getLogger(__name__)


@shared_task
def ingest_custom_boundary_task(req_id, geojson_fc, datasets, user_id=None):
    """
    Ingest a custom boundary GeoJSON for an existing Request (status=3 on entry).

    On success sets the request to status=-1 (queued).
    On failure sets status=-2 (error) and records the error message in req.data.
    """
    try:
        req = Request.objects.get(id=req_id)
    except Request.DoesNotExist:
        logger.error("ingest_custom_boundary_task: Request %s not found", req_id)
        return

    user = None
    if user_id is not None:
        try:
            user = get_user_model().objects.get(id=user_id)
        except get_user_model().DoesNotExist:
            pass

    try:
        task_count, warnings = ingest_custom_boundary(geojson_fc, datasets, req, user)
        logger.info(
            "Ingested custom boundary for request %s: %d tasks, %d warnings",
            req_id,
            task_count,
            len(warnings),
        )
    except ValueError as exc:
        logger.warning("Custom boundary ingestion failed for request %s: %s", req_id, exc)
        req.status = -2
        req.data = {**req.data, "error": str(exc)}
        req.save(update_fields=["status", "data"])
    except Exception as exc:
        logger.exception("Unexpected error ingesting custom boundary for request %s", req_id)
        req.status = -2
        req.data = {**req.data, "error": str(exc)}
        req.save(update_fields=["status", "data"])
        raise
