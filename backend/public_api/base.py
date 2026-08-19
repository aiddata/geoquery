from rest_framework.permissions import AllowAny

from .authentication import PublicApiKeyAuthentication
from .exceptions import public_api_exception_handler
from .throttling import PublicApiThrottle


class PublicApiBaseMixin:
    """Shared DRF configuration for every public_api view.

    Bundles the auth seam, IP/consumer-tier throttle, AllowAny permission
    (open during beta — see PublicApiKeyAuthentication), and the public
    error envelope, so each view only needs to declare this mixin plus
    its own serializer/queryset.
    """

    authentication_classes = [PublicApiKeyAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [PublicApiThrottle]

    def get_exception_handler(self):
        return public_api_exception_handler
