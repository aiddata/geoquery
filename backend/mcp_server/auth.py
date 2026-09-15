"""GitHub sign-in, mapped onto GeoQuery accounts.

The web app already authenticates with GitHub through allauth, and catalog
grants, request ownership and email claims all hang off ``accounts.User``. The
MCP server therefore does not get its own notion of identity: it authenticates
with GitHub through FastMCP's OAuth proxy and then resolves that GitHub
identity to the *same* ``User`` row the website would have used, so a catalog
grant made in the admin applies in both places without anyone syncing
anything.

Resolution order, most to least certain:

1. A ``SocialAccount(provider="github", uid=<github id>)`` already exists --
   the same lookup allauth does. This covers anyone who has signed in on the
   website.
2. A *verified* ``EmailAddress`` matches the GitHub account's verified email.
   The user exists but has never connected GitHub; connect it now. This
   mirrors ``SOCIALACCOUNT_EMAIL_AUTHENTICATION`` on the web side.
3. Nothing matches: provision an account (when enabled), and immediately claim
   any anonymous requests previously submitted under that address.

This needs a **second GitHub OAuth App**, distinct from the website's: a GitHub
OAuth App has exactly one callback URL, and this one's is
``{MCP_BASE_URL}/auth/callback``.
"""

from __future__ import annotations

import logging

import httpx2
from django.conf import settings
from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)

# GitHub's /user response omits `email` whenever the profile address is
# private, which is the default for many accounts. The `user:email` scope lets
# us read the verified list instead. GitHubProvider does not do this itself,
# so without the fallback a large fraction of users would resolve to "no
# email" -- unable to be matched to an existing account, unable to be
# provisioned, and unable to have their past requests claimed.
_GITHUB_EMAILS_URL = "https://api.github.com/user/emails"
_GITHUB_TIMEOUT_SECONDS = 10


class AuthenticationRequired(Exception):
    """No usable GeoQuery identity for this caller.

    The message is shown to the model, and through it to the user, so it
    always names the concrete next step rather than just refusing.
    """


def make_auth_provider():
    """The GitHub OAuth provider, or ``None`` when not configured.

    ``None`` means the server runs unauthenticated. ``run_mcp`` refuses to
    start that way outside DEBUG unless ``MCP_AUTH_DISABLED`` is set, which
    turns authentication off explicitly regardless of the GitHub credentials.
    """
    if settings.MCP_AUTH_DISABLED:
        return None
    if not (settings.MCP_GITHUB_CLIENT_ID and settings.MCP_GITHUB_CLIENT_SECRET):
        return None

    from fastmcp.server.auth.providers.github import GitHubProvider

    return GitHubProvider(
        client_id=settings.MCP_GITHUB_CLIENT_ID,
        client_secret=settings.MCP_GITHUB_CLIENT_SECRET,
        base_url=settings.MCP_BASE_URL,
        redirect_path="/auth/callback",
        # read:user for the profile, user:email for the verified address list
        # -- the same pair the website's provider asks for.
        required_scopes=["read:user", "user:email"],
        # Left to derive from the client secret when unset. Setting it
        # explicitly matters for a deployment that rotates the GitHub secret:
        # without it, rotation invalidates every issued token and every stored
        # client registration at once.
        jwt_signing_key=settings.MCP_JWT_SIGNING_KEY or None,
    )


def _verified_github_email(access_token: str) -> str | None:
    """The account's primary verified email, via GitHub's /user/emails.

    Unverified addresses are ignored: claiming a GeoQuery account, or the
    requests submitted under an address, on the strength of an unverified
    email would let anyone take over an account by adding someone else's
    address to their GitHub profile.
    """
    try:
        response = httpx2.get(
            _GITHUB_EMAILS_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "GeoQuery-MCP",
            },
            timeout=_GITHUB_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            logger.warning(
                "GitHub /user/emails returned %s", response.status_code
            )
            return None
        entries = response.json()
    except Exception:
        logger.exception("Could not read verified emails from GitHub")
        return None

    verified = [e for e in entries if e.get("verified") and e.get("email")]
    if not verified:
        return None
    primary = next((e for e in verified if e.get("primary")), verified[0])
    return primary["email"]


def _claims_from_token(token) -> dict:
    """Normalize a FastMCP AccessToken into the fields we resolve on."""
    claims = getattr(token, "claims", None) or {}
    return {
        "sub": str(claims.get("sub") or getattr(token, "subject", "") or ""),
        "login": claims.get("login") or "",
        "name": claims.get("name") or "",
        "email": claims.get("email") or "",
        "access_token": getattr(token, "token", None),
    }


def resolve_or_provision_user(claims: dict):
    """Map GitHub claims onto an ``accounts.User``.

    Raises ``AuthenticationRequired`` when no account can be resolved and
    provisioning is off or the GitHub account exposes no verified email.
    """
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount

    uid = claims.get("sub")
    if not uid:
        raise AuthenticationRequired(
            "The access token carries no GitHub user id. Sign in again."
        )

    # 1. Already connected.
    account = (
        SocialAccount.objects.filter(provider="github", uid=uid)
        .select_related("user")
        .first()
    )
    if account is not None:
        if not account.user.is_active:
            raise AuthenticationRequired(
                "This GeoQuery account is disabled. Contact "
                "geo@aiddata.wm.edu if that is unexpected."
            )
        return account.user

    # The email claim is frequently absent (private profile), so fall back to
    # the verified list before concluding there is nothing to match on.
    email = claims.get("email")
    if not email and claims.get("access_token"):
        email = _verified_github_email(claims["access_token"])

    account_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/account"
    if not email:
        raise AuthenticationRequired(
            "GitHub did not share a verified email address for this account, "
            "so it cannot be matched to a GeoQuery account. Add and verify an "
            f"email on GitHub, or sign in at {account_url} first."
        )

    # 2. A verified address on an existing account: connect GitHub to it.
    existing = (
        EmailAddress.objects.filter(email__iexact=email, verified=True)
        .select_related("user")
        .first()
    )
    if existing is not None:
        if not existing.user.is_active:
            raise AuthenticationRequired(
                "This GeoQuery account is disabled. Contact "
                "geo@aiddata.wm.edu if that is unexpected."
            )
        SocialAccount.objects.get_or_create(
            provider="github",
            uid=uid,
            defaults={"user": existing.user, "extra_data": {}},
        )
        return existing.user

    # 3. Provision.
    if not settings.MCP_AUTO_PROVISION_USERS:
        raise AuthenticationRequired(
            f"No GeoQuery account for {email}. Create one at {account_url}, "
            "then reconnect."
        )
    return _provision_user(uid, email, claims)


def _provision_user(uid: str, email: str, claims: dict):
    """Create a user, its verified email, and its GitHub link, atomically.

    All three rows commit together or none do: a User without its
    EmailAddress would be invisible to ``requests_for_user`` and could never
    claim its own history, and one without its SocialAccount would be
    re-provisioned (and collide on the unique email) at the next sign-in.
    """
    from allauth.account.adapter import get_adapter
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount
    from django.contrib.auth import get_user_model

    from accounts.claims import claim_requests_for_user

    User = get_user_model()
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                # Through the adapter rather than allauth.utils directly, so a
                # project that customises username generation (accounts.adapter)
                # governs MCP sign-ups too.
                username=get_adapter().generate_unique_username(
                    [claims.get("login"), email, "user"]
                ),
                email=email,
            )
            user.set_unusable_password()
            if claims.get("name"):
                # Best effort: GitHub gives one display name, not given/family.
                user.first_name = claims["name"][:150]
            user.save()
            EmailAddress.objects.create(
                user=user, email=email, verified=True, primary=True
            )
            SocialAccount.objects.create(
                provider="github", uid=uid, user=user, extra_data={}
            )
    except IntegrityError:
        # Lost a race with a concurrent first sign-in, or an existing user
        # holds this email with no verified EmailAddress row. Re-resolve
        # rather than surfacing a database error.
        account = (
            SocialAccount.objects.filter(provider="github", uid=uid)
            .select_related("user")
            .first()
        )
        if account is not None:
            return account.user
        raise AuthenticationRequired(
            f"An account already exists for {email} but is not connected to "
            f"GitHub. Sign in at {settings.FRONTEND_BASE_URL.rstrip('/')}"
            "/account and verify the address, then reconnect."
        ) from None

    claimed = claim_requests_for_user(user)
    logger.info(
        "Provisioned MCP user %s from GitHub (%s); claimed %d prior request(s)",
        user.pk,
        claims.get("login") or uid,
        claimed,
    )
    return user


def resolve_current_user():
    """The ``accounts.User`` for the in-flight tool call.

    Read through ``mcp_server.tools``' ``current_user`` dependency rather than
    called directly. Unauthenticated calls are already rejected by FastMCP at
    the transport when a provider is configured; the explicit check here is
    what keeps a misconfiguration from silently serving every caller as
    anonymous.
    """
    from fastmcp.server.dependencies import get_access_token

    token = get_access_token()
    if token is None:
        raise AuthenticationRequired(
            "Not signed in. Reconnect the GeoQuery MCP server and complete the "
            "GitHub sign-in."
        )
    return resolve_or_provision_user(_claims_from_token(token))
