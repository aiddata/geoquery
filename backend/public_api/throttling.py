from django.core.exceptions import ImproperlyConfigured
from rest_framework.throttling import SimpleRateThrottle


class PublicApiThrottle(SimpleRateThrottle):
    """Throttles /api/public/v1/ requests.

    Falls back to per-IP throttling under the `public_api_anon` scope
    today, since PublicApiKeyAuthentication never resolves a real
    consumer yet. Once it does, a resolved PublicApiConsumer's own
    rate_limit_tier becomes the throttle scope automatically — as long as
    that tier has a configured rate in DEFAULT_THROTTLE_RATES. An
    unrecognized tier degrades safely to the anonymous rate rather than
    raising, since this seam can't know what tier names a not-yet-built
    accounts feature will eventually define.
    """

    scope = "public_api_anon"

    def __init__(self):
        # Deliberately skip SimpleRateThrottle.__init__, which eagerly
        # calls get_rate()/parse_rate() against the class-level default
        # scope at construction time. This throttle computes its rate
        # per-request in get_cache_key() instead (scope depends on the
        # resolved consumer), so nothing needs to happen here. Mirrors
        # DRF's own ScopedRateThrottle for the same reason.
        pass

    def get_cache_key(self, request, view):
        # authenticate() returns (consumer, key), which DRF unpacks as
        # (request.user, request.auth) — so the resolved consumer is on
        # request.user, not request.auth.
        consumer = getattr(request, "user", None)
        if consumer is not None and getattr(consumer, "rate_limit_tier", None):
            self.scope = consumer.rate_limit_tier
            ident = f"consumer:{consumer.id}"
        else:
            self.scope = "public_api_anon"
            ident = self.get_ident(request)

        try:
            self.rate = self.get_rate()
        except ImproperlyConfigured:
            self.scope = "public_api_anon"
            self.rate = self.get_rate()

        self.num_requests, self.duration = self.parse_rate(self.rate)

        return self.cache_format % {"scope": self.scope, "ident": ident}
