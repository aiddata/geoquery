import logging

from celery import shared_task

from analytics.models import Request
from analytics.services import NoExtractTasksError, materialize_request

logger = logging.getLogger(__name__)


@shared_task
def materialize_request_tasks(request_id):
    """Build ExtractTasks and RequestMap rows for a Request submitted at
    status=4 (materializing), then move it to status=-1 (queued).

    materialize_request's status update is a request.save(...) call, which
    fires analytics.signals.on_request_submitted -- that's what actually
    schedules the processing-dispatch chain once materialization finishes;
    this task doesn't need to do it explicitly.

    On failure sets status=-2 (error) and records the error message in
    request.data, the same shape analytics.tasks.ingest.
    ingest_custom_boundary_task already uses for this Request's sibling
    async-prep path (custom boundary ingestion, status=3 instead of 4).
    """
    try:
        req = Request.objects.get(id=request_id)
    except Request.DoesNotExist:
        logger.error("materialize_request_tasks: Request %s not found", request_id)
        return

    try:
        materialize_request(req)
        logger.info("Materialized tasks for request %s", request_id)
    except NoExtractTasksError as exc:
        logger.warning(
            "No extract tasks resolvable for request %s at materialization "
            "time: %s",
            request_id, exc.warnings,
        )
        Request.objects.filter(id=request_id).update(
            status=-2,
            data={**req.data, "error": str(exc), "error_detail": exc.warnings},
        )
        return
    except Exception as exc:
        logger.exception("Unexpected error materializing request %s", request_id)
        Request.objects.filter(id=request_id).update(
            status=-2, data={**req.data, "error": str(exc)}
        )
        raise
