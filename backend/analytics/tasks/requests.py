import logging

from celery import chain, shared_task

from analytics.models import Request
from analytics.services import NoExtractTasksError, materialize_request

logger = logging.getLogger(__name__)


@shared_task
def materialize_request_tasks(request_id):
    """Build ExtractTasks and RequestMap rows for a Request submitted at
    status=4 (materializing), then move it to status=-1 (queued).

    On success, explicitly fires the same dispatch chain
    analytics.signals.on_request_submitted fires on Request creation. That
    signal already ran when the Request was created, but harmlessly, since
    the completion sweep only looks at status=-1/0 and found nothing to do
    at status=4 -- this is the real "go process this" trigger, run once
    materialization has actually finished.

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

    from analytics.tasks.maintenance import (
        dispatch_processing_tasks,
        process_user_requests,
    )

    chain(process_user_requests.si(), dispatch_processing_tasks.si()).delay()
