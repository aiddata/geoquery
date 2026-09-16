"""GeoQuery sign-in for the MCP server.

The MCP server has no notion of identity of its own. It is an OAuth client of
GeoQuery's own OpenID Connect provider (``allauth.idp.oidc``, mounted at
``/api/idp/``), so a chat client connecting here sends its user to the
GeoQuery website to sign in, exactly as if they were visiting the site. They
come back as the *same* ``accounts.User`` the website would have used, which
is what makes a catalog grant made in the admin apply in both places without
anyone syncing anything.

Whichever upstream provider the website uses -- GitHub today, possibly others
later -- is therefore none of this module's business. The token carries a
``sub`` claim that is the GeoQuery user's primary key, so resolving a caller
is a lookup rather than a matching heuristic: by the time a token exists, the
account does too.

Two base URLs are in play, and they are not interchangeable:

* ``FRONTEND_BASE_URL`` is where the *browser* goes, so it is the base for
  ``/authorize``.
* ``MCP_OIDC_INTERNAL_URL`` is where *this process* goes for the back-channel
  token, revocation and JWKS calls. In a Kubernetes deployment it is the
  backend Service, which the browser cannot reach and network policy requires
  this pod to use.

Discovery is deliberately not used to find those endpoints. allauth builds the
URLs in its discovery document from the requesting Host, so fetching it over
the internal URL would advertise an in-cluster hostname as the authorization
endpoint and send the browser somewhere it cannot go.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Paths of allauth's OIDC endpoints under the /api/idp/ mount. Hard-coded
# rather than reversed, because the MCP server builds them against two
# different bases and reverse() would only ever give a path.
AUTHORIZE_PATH = "/api/idp/identity/o/authorize"
TOKEN_PATH = "/api/idp/identity/o/api/token"
REVOKE_PATH = "/api/idp/identity/o/api/revoke"
JWKS_PATH = "/api/idp/.well-known/jwks.json"

# Only openid. The server identifies the caller by `sub` alone and reads name
# and email from the account, so the consent page asks for nothing more than
# "View your user ID". Must match ensure_mcp_oidc_client.SCOPES, which is what
# the provider allows this client to request.
SCOPES = ["openid"]


class AuthenticationRequired(Exception):
    """No usable GeoQuery identity for this caller.

    The message is shown to the model, and through it to the user, so it
    always names the concrete next step rather than just refusing.
    """


def _issuer() -> str:
    """The value ``accounts.oidc.GeoQueryOIDCAdapter`` puts in ``iss``."""
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/api/idp"


def make_auth_provider():
    """The OAuth provider, or ``None`` when not configured.

    ``None`` means the server runs unauthenticated. ``run_mcp`` refuses to
    start that way outside DEBUG unless ``MCP_AUTH_DISABLED`` is set, which
    turns authentication off explicitly regardless of the client credentials.
    """
    if settings.MCP_AUTH_DISABLED:
        return None
    if not (settings.MCP_OIDC_CLIENT_ID and settings.MCP_OIDC_CLIENT_SECRET):
        return None

    from fastmcp.server.auth.oauth_proxy import OAuthProxy
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    public = settings.FRONTEND_BASE_URL.rstrip("/")
    internal = settings.MCP_OIDC_INTERNAL_URL.rstrip("/")

    # Access tokens are RS256 JWTs (IDP_OIDC_ACCESS_TOKEN_FORMAT), verified
    # offline against the provider's JWKS. No audience: allauth only sets
    # `aud` when resource indicators are in play, which they are not here.
    verifier = JWTVerifier(
        jwks_uri=f"{internal}{JWKS_PATH}",
        issuer=_issuer(),
        algorithm="RS256",
    )

    return OAuthProxy(
        upstream_authorization_endpoint=f"{public}{AUTHORIZE_PATH}",
        upstream_token_endpoint=f"{internal}{TOKEN_PATH}",
        upstream_revocation_endpoint=f"{internal}{REVOKE_PATH}",
        upstream_client_id=settings.MCP_OIDC_CLIENT_ID,
        upstream_client_secret=settings.MCP_OIDC_CLIENT_SECRET,
        token_verifier=verifier,
        base_url=settings.MCP_BASE_URL,
        redirect_path="/auth/callback",
        valid_scopes=SCOPES,
        # GeoQuery's own consent page is the only prompt the user sees. That
        # page names this server, not the chat client that is connecting --
        # every client shares this one upstream registration -- so the
        # redirect allowlist below is what actually constrains who may
        # complete a flow.
        require_authorization_consent="external",
        allowed_client_redirect_uris=[
            "http://localhost:*",
            "http://127.0.0.1:*",
            "https://claude.ai/api/mcp/auth_callback",
            "https://claude.com/api/mcp/auth_callback",
        ],
        # Left to derive from the client secret when unset. Setting it
        # explicitly matters for a deployment that rotates the OIDC client
        # secret: without it, rotation invalidates every issued token and
        # every stored client registration at once.
        jwt_signing_key=settings.MCP_JWT_SIGNING_KEY or None,
    )


def _claims_from_token(token) -> dict:
    """Normalize a FastMCP AccessToken into the fields we resolve on.

    Only ``sub`` -- allauth puts name and email in the ID token and on the
    userinfo endpoint, not in the access token, and nothing here needs them
    anyway: the account they would describe is already in the database.
    """
    claims = getattr(token, "claims", None) or {}
    return {"sub": str(claims.get("sub") or getattr(token, "subject", "") or "")}


def resolve_user(claims: dict):
    """The ``accounts.User`` named by the token's ``sub`` claim.

    ``sub`` is the user's primary key -- allauth's OIDC adapter stringifies it
    -- so there is nothing to match or provision here. Anyone holding a token
    signed in on the website, which is also where an account gets created and
    where past requests submitted under a verified address are claimed (see
    ``accounts.signals``).
    """
    from django.contrib.auth import get_user_model

    sub = claims.get("sub")
    if not sub:
        raise AuthenticationRequired(
            "The access token carries no GeoQuery user id. Sign in again."
        )

    try:
        pk = int(sub)
    except (TypeError, ValueError):
        raise AuthenticationRequired(
            "The access token's user id is not in the expected form. Sign in "
            "again."
        ) from None

    account_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/account"
    user = get_user_model().objects.filter(pk=pk).first()
    if user is None:
        raise AuthenticationRequired(
            "This token refers to a GeoQuery account that no longer exists. "
            f"Sign in again at {account_url}."
        )
    if not user.is_active:
        raise AuthenticationRequired(
            "This GeoQuery account is disabled. Contact geo@aiddata.wm.edu if "
            "that is unexpected."
        )
    return user


async def resolve_current_user():
    """The ``accounts.User`` for the in-flight tool call.

    Read through the ``user`` dependency ``mcp_server.tools`` builds rather
    than called directly. Unauthenticated calls are already rejected by
    FastMCP at the transport when a provider is configured; the explicit check
    here is what keeps a misconfiguration from silently serving every caller
    as anonymous.

    Two things about running as a ``Depends()`` shape this function:

    * FastMCP resolves dependencies on the event loop, where the Django ORM
      refuses to run. The account lookup therefore goes to a worker thread,
      inside ``django_db`` so that thread releases its connection on the way
      out (see ``mcp_server.db``).
    * Any non-FastMCP exception raised here is wrapped by FastMCP into an
      opaque "Failed to resolve dependency 'user'" and masked from the model.
      ``AuthenticationRequired`` is re-raised as a ``ToolError`` so the model
      sees the actual next step instead.
    """
    from asgiref.sync import sync_to_async
    from fastmcp.exceptions import ToolError
    from fastmcp.server.dependencies import get_access_token

    from mcp_server.db import django_db

    # Read the token here, on the event loop: it lives in a context variable
    # bound to the request, which is where it is guaranteed to be visible.
    token = get_access_token()
    if token is None:
        raise ToolError(
            "Not signed in. Reconnect the GeoQuery MCP server and complete "
            "the GeoQuery sign-in."
        )
    claims = _claims_from_token(token)

    def lookup():
        with django_db():
            return resolve_user(claims)

    try:
        return await sync_to_async(lookup, thread_sensitive=False)()
    except AuthenticationRequired as exc:
        raise ToolError(str(exc)) from exc
