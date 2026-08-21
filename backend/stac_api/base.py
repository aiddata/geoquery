from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle


class StacApiBaseMixin:
    """Shared DRF configuration for every stac_api view.

    Fully open (no auth seam) and unconditionally CORS-enabled — unlike
    public_api, there is no PublicApiKeyAuthentication stub here: STAC
    catalogs are conventionally public, and this layer never serves
    protected data, only metadata. The wildcard CORS header is what lets
    browser-based STAC clients (e.g. STAC Browser, hosted on its own
    origin) read this catalog at all; see the design spec's CORS section
    for why this can't just reuse the app-wide corsheaders config used by
    the cookie-authenticated internal frontend.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "stac_api_anon"

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response
