from dataclasses import dataclass

from rest_framework.authentication import BaseAuthentication


@dataclass
class PublicApiConsumer:
    """Minimal shape a resolved public API credential must satisfy.

    The accounts feature (built separately) will supply the real lookup
    behind resolve_api_key(); this dataclass documents the interface it
    needs to produce, not a persisted model.
    """

    id: int
    rate_limit_tier: str
    is_active: bool


def resolve_api_key(key: str) -> PublicApiConsumer | None:
    """Resolve an API key string to a consumer.

    Stubbed until the accounts feature provides real key storage and
    issuance. Always returns None, so every request currently falls
    through to anonymous access. Swapping in a real lookup here is the
    only change needed to activate authenticated access.
    """
    return None


class PublicApiKeyAuthentication(BaseAuthentication):
    """Authenticates public_api requests via `Authorization: Api-Key <key>`.

    Never raises: an invalid or missing key simply yields no credentials,
    since every public_api view currently sets permission_classes to
    AllowAny (see PublicApiBaseMixin). Once real keys exist, an unresolved
    key still just means "anonymous" here — enforcing that a key is
    *required* is a permission-class concern, not this class's job.
    """

    keyword = "Api-Key"

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        prefix = f"{self.keyword} "
        if not auth_header.startswith(prefix):
            return None

        key = auth_header[len(prefix):].strip()
        if not key:
            return None

        consumer = resolve_api_key(key)
        if consumer is None or not consumer.is_active:
            return None

        return (consumer, key)
