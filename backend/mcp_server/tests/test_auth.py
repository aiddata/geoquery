"""Mapping an OIDC token onto a GeoQuery account.

The rule this protects: a token issued by GeoQuery's own provider must land on
the *same* ``accounts.User`` the website would have used, so a catalog grant
made in the admin applies in both places. Because ``sub`` is the user's
primary key, the risk is no longer mismatching identities but accepting a
``sub`` that should have been refused -- one naming a deleted or disabled
account, or one that is not a user id at all.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings

from mcp_server.auth import (
    AuthenticationRequired,
    _claims_from_token,
    make_auth_provider,
    resolve_user,
)

User = get_user_model()


def claims(**overrides):
    base = {"sub": "1"}
    base.update(overrides)
    return base


class ResolveUserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mona", email="mona@example.com"
        )

    def test_resolves_the_user_named_by_sub(self):
        resolved = resolve_user(claims(sub=str(self.user.pk)))
        self.assertEqual(resolved, self.user)

    def test_does_not_create_an_account(self):
        before = User.objects.count()
        resolve_user(claims(sub=str(self.user.pk)))
        self.assertEqual(User.objects.count(), before)

    def test_a_disabled_account_is_refused(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(AuthenticationRequired) as caught:
            resolve_user(claims(sub=str(self.user.pk)))
        self.assertIn("disabled", str(caught.exception))

    def test_an_unknown_sub_is_refused(self):
        with self.assertRaises(AuthenticationRequired) as caught:
            resolve_user(claims(sub=str(self.user.pk + 10_000)))
        self.assertIn("no longer exists", str(caught.exception))

    def test_an_empty_sub_is_refused(self):
        with self.assertRaises(AuthenticationRequired) as caught:
            resolve_user(claims(sub=""))
        self.assertIn("no GeoQuery user id", str(caught.exception))

    def test_a_non_numeric_sub_is_refused(self):
        # A token minted for some other kind of subject must not fall through
        # to a lookup that happens to succeed.
        with self.assertRaises(AuthenticationRequired) as caught:
            resolve_user(claims(sub="octocat"))
        self.assertIn("not in the expected form", str(caught.exception))

    @override_settings(FRONTEND_BASE_URL="https://geoquery.org/")
    def test_refusals_point_at_the_account_page(self):
        with self.assertRaises(AuthenticationRequired) as caught:
            resolve_user(claims(sub=str(self.user.pk + 10_000)))
        self.assertIn("https://geoquery.org/account", str(caught.exception))


class ClaimsFromTokenTests(TestCase):
    def test_reads_the_sub_claim(self):
        token = mock.Mock(
            claims={"sub": "7", "scope": "openid"}, subject="7", token="at-abc"
        )
        self.assertEqual(_claims_from_token(token), {"sub": "7"})

    def test_falls_back_to_subject_when_no_sub_claim(self):
        token = mock.Mock(claims={}, subject="7", token="at-abc")
        self.assertEqual(_claims_from_token(token), {"sub": "7"})

    def test_missing_claims_become_an_empty_sub(self):
        token = mock.Mock(claims=None, subject="", token=None)
        self.assertEqual(_claims_from_token(token), {"sub": ""})


class AuthProviderTests(TestCase):
    """When the server is allowed to run without authentication.

    ``None`` is the signal ``run_mcp`` checks before refusing to start, so
    these cases decide whether a deployment comes up unauthenticated.
    """

    @override_settings(
        MCP_OIDC_CLIENT_ID="", MCP_OIDC_CLIENT_SECRET="", MCP_AUTH_DISABLED=False
    )
    def test_no_provider_without_client_credentials(self):
        self.assertIsNone(make_auth_provider())

    @override_settings(
        MCP_OIDC_CLIENT_ID="geoquery-mcp",
        MCP_OIDC_CLIENT_SECRET="",
        MCP_AUTH_DISABLED=False,
    )
    def test_no_provider_with_only_a_client_id(self):
        self.assertIsNone(make_auth_provider())

    @override_settings(
        MCP_OIDC_CLIENT_ID="geoquery-mcp",
        MCP_OIDC_CLIENT_SECRET="s3cret",
        MCP_AUTH_DISABLED=True,
    )
    def test_auth_disabled_wins_over_configured_credentials(self):
        self.assertIsNone(make_auth_provider())


class AuthProviderEndpointTests(TestCase):
    """The browser-facing and back-channel URLs must not be the same base.

    This is the bug the split exists to prevent: if /authorize were built from
    the internal URL, a deployment would redirect people's browsers to a
    hostname that only resolves inside the cluster.
    """

    @override_settings(
        MCP_OIDC_CLIENT_ID="geoquery-mcp",
        MCP_OIDC_CLIENT_SECRET="s3cret",
        MCP_AUTH_DISABLED=False,
        MCP_BASE_URL="https://mcp.geoquery.org",
        FRONTEND_BASE_URL="https://geoquery.org",
        MCP_OIDC_INTERNAL_URL="http://geoquery-backend.aiddata.svc.cluster.local",
        MCP_JWT_SIGNING_KEY="signing-key",
    )
    def test_authorize_is_public_and_token_is_internal(self):
        provider = make_auth_provider()
        self.assertIsNotNone(provider)
        self.assertEqual(
            provider._upstream_authorization_endpoint,
            "https://geoquery.org/api/idp/identity/o/authorize",
        )
        self.assertEqual(
            provider._upstream_token_endpoint,
            "http://geoquery-backend.aiddata.svc.cluster.local"
            "/api/idp/identity/o/api/token",
        )


class ResolveCurrentUserTests(TransactionTestCase):
    """``resolve_current_user`` as FastMCP actually runs it: as a ``Depends()``
    resolved on the event loop, with the outcome reported to the model.

    Regression: an earlier version did the ORM lookup synchronously on the
    loop, so every authenticated call died with Django's
    ``SynchronousOnlyOperation`` -- and because FastMCP wraps resolver errors,
    all the model ever saw was "Failed to resolve dependency 'user'".

    ``TransactionTestCase`` because the lookup runs in a worker thread with
    its own connection, which cannot see rows still inside ``TestCase``'s
    uncommitted transaction.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="mona", email="mona@example.com"
        )

    @staticmethod
    def _resolve(token):
        import asyncio

        from fastmcp.dependencies import Depends
        from fastmcp.server.dependencies import resolve_dependencies

        from mcp_server.auth import resolve_current_user

        def tool(user=Depends(resolve_current_user)):
            return user

        async def go():
            with mock.patch(
                "fastmcp.server.dependencies.get_access_token", return_value=token
            ):
                async with resolve_dependencies(tool, {}) as arguments:
                    return arguments["user"]

        return asyncio.run(go())

    def test_resolves_the_user_from_the_event_loop(self):
        token = mock.Mock(claims={"sub": str(self.user.pk)})
        self.assertEqual(self._resolve(token), self.user)

    def test_missing_token_is_reported_to_the_model(self):
        from fastmcp.exceptions import ToolError

        with self.assertRaises(ToolError) as caught:
            self._resolve(None)
        self.assertIn("Not signed in", str(caught.exception))

    def test_a_refused_account_is_reported_to_the_model(self):
        from fastmcp.exceptions import ToolError

        token = mock.Mock(claims={"sub": str(self.user.pk + 10_000)})
        with self.assertRaises(ToolError) as caught:
            self._resolve(token)
        self.assertIn("no longer exists", str(caught.exception))
