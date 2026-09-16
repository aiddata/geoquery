"""Adapter for GeoQuery's OpenID Connect provider.

The one thing it changes is the issuer. allauth derives ``iss`` from the
incoming request's Host (``build_absolute_uri("/")``), which would make it
whatever hostname happened to be used: the public site when a browser hits
/authorize, but the in-cluster Service name when the MCP server calls the
token endpoint over its back channel. Tokens minted by the same provider
would then carry different issuers depending on who asked for them, and the
MCP server -- which pins ``iss`` when verifying -- would reject half of them.

Pinning it to the public base also makes the issuer agree with where the
discovery document is actually served (``{issuer}/.well-known/openid-configuration``),
which is what OpenID Connect Discovery expects and what any third-party client
would go looking for.
"""

from allauth.idp.oidc.adapter import DefaultOIDCAdapter
from django.conf import settings


class GeoQueryOIDCAdapter(DefaultOIDCAdapter):
    def get_issuer(self) -> str:
        return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/api/idp"
