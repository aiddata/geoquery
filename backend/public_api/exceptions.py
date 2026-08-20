from rest_framework.views import exception_handler as drf_exception_handler


def public_api_exception_handler(exc, context):
    """Wraps DRF's default error response in a stable {"error": {...}} envelope.

    Scoped to public_api views only (see PublicApiBaseMixin) so internal
    /api/* endpoints keep DRF's default error format unchanged.
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and set(detail.keys()) == {"detail"}:
        message = detail["detail"]
    else:
        message = detail

    response.data = {
        "error": {
            "code": response.status_code,
            "message": message,
        }
    }
    return response
