from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class RequestTokenThrottle(AnonRateThrottle):
    """Throttle for the magic-link email endpoint."""

    scope = "request_token"


class RequestSubmitThrottle(AnonRateThrottle):
    """Throttle for the request submission endpoint."""

    scope = "request_submit"


class ShareCreateThrottle(SimpleRateThrottle):
    """Throttle for creating share links, per user or, signed out, per IP."""

    scope = "share_create"

    def get_cache_key(self, request, view):
        ident = request.user.pk if request.user.is_authenticated else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
