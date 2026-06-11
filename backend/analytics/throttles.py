from rest_framework.throttling import AnonRateThrottle


class RequestTokenThrottle(AnonRateThrottle):
    """Throttle for the magic-link email endpoint."""
    scope = "request_token"


class RequestSubmitThrottle(AnonRateThrottle):
    """Throttle for the request submission endpoint."""
    scope = "request_submit"
