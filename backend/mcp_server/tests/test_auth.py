"""Mapping a GitHub identity onto a GeoQuery account.

The rule this protects: a GitHub sign-in must land on the *same*
``accounts.User`` the website would have used, so a catalog grant made in the
admin applies in both places, and someone's past anonymous requests become
theirs. Getting it wrong either duplicates accounts or, worse, hands one
person another's requests.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount

from analytics.models import Request
from mcp_server.auth import (
    AuthenticationRequired,
    _claims_from_token,
    make_auth_provider,
    resolve_or_provision_user,
)

User = get_user_model()

GITHUB_UID = "4242"


def claims(**overrides):
    base = {
        "sub": GITHUB_UID,
        "login": "octocat",
        "name": "Mona Lisa",
        "email": "mona@example.com",
        "access_token": None,
    }
    base.update(overrides)
    return base


class ExistingSocialAccountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mona", email="mona@example.com", password="x"
        )
        SocialAccount.objects.create(
            provider="github", uid=GITHUB_UID, user=self.user, extra_data={}
        )

    def test_resolves_to_the_connected_account(self):
        self.assertEqual(resolve_or_provision_user(claims()), self.user)

    def test_resolves_even_when_github_shares_no_email(self):
        """A private profile is common; an already-connected account needs no
        email to be identified."""
        self.assertEqual(
            resolve_or_provision_user(claims(email=None)), self.user
        )

    def test_a_disabled_account_is_refused_with_a_reason(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        with self.assertRaises(AuthenticationRequired) as ctx:
            resolve_or_provision_user(claims())

        self.assertIn("disabled", str(ctx.exception))

    def test_no_second_account_is_created(self):
        resolve_or_provision_user(claims())

        self.assertEqual(User.objects.count(), 1)


class VerifiedEmailMatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mona", email="mona@example.com", password="x"
        )
        EmailAddress.objects.create(
            user=self.user, email="mona@example.com", verified=True, primary=True
        )

    def test_connects_github_to_the_existing_account(self):
        resolved = resolve_or_provision_user(claims())

        self.assertEqual(resolved, self.user)
        self.assertTrue(
            SocialAccount.objects.filter(
                provider="github", uid=GITHUB_UID, user=self.user
            ).exists()
        )

    def test_match_is_case_insensitive(self):
        self.assertEqual(
            resolve_or_provision_user(claims(email="MONA@Example.com")), self.user
        )

    def test_an_unverified_address_does_not_match(self):
        """Matching on an unverified address would let anyone take over an
        account by adding its email to their GitHub profile."""
        EmailAddress.objects.update(verified=False)

        with override_settings(MCP_AUTO_PROVISION_USERS=False):
            with self.assertRaises(AuthenticationRequired):
                resolve_or_provision_user(claims())


class ProvisioningTests(TestCase):
    def test_creates_a_user_with_a_verified_primary_email_and_github_link(self):
        user = resolve_or_provision_user(claims())

        self.assertEqual(user.email, "mona@example.com")
        self.assertTrue(
            EmailAddress.objects.filter(
                user=user, email="mona@example.com", verified=True, primary=True
            ).exists()
        )
        self.assertTrue(
            SocialAccount.objects.filter(provider="github", uid=GITHUB_UID).exists()
        )
        self.assertFalse(user.has_usable_password())

    def test_claims_prior_anonymous_requests_under_the_same_address(self):
        mine = Request.objects.create(contact="MONA@example.com")
        someone_else = Request.objects.create(contact="other@example.com")

        user = resolve_or_provision_user(claims())

        mine.refresh_from_db()
        someone_else.refresh_from_db()
        self.assertEqual(mine.user, user)
        self.assertIsNone(someone_else.user)

    def test_a_request_already_owned_is_not_reassigned(self):
        owner = User.objects.create_user(
            username="owner", email="owner@example.com", password="x"
        )
        theirs = Request.objects.create(contact="mona@example.com", user=owner)

        resolve_or_provision_user(claims())

        theirs.refresh_from_db()
        self.assertEqual(theirs.user, owner)

    def test_usernames_do_not_collide(self):
        User.objects.create_user(
            username="octocat", email="other@example.com", password="x"
        )

        user = resolve_or_provision_user(claims())

        self.assertNotEqual(user.username, "octocat")
        self.assertEqual(user.email, "mona@example.com")

    @override_settings(MCP_AUTO_PROVISION_USERS=False)
    def test_provisioning_can_be_turned_off(self):
        with self.assertRaises(AuthenticationRequired) as ctx:
            resolve_or_provision_user(claims())

        self.assertIn("/account", str(ctx.exception))
        self.assertEqual(User.objects.count(), 0)

    def test_nothing_is_created_when_there_is_no_verified_email(self):
        with self.assertRaises(AuthenticationRequired) as ctx:
            resolve_or_provision_user(claims(email=None))

        self.assertIn("verified email", str(ctx.exception))
        self.assertEqual(User.objects.count(), 0)

    def test_a_token_with_no_github_id_is_refused(self):
        with self.assertRaises(AuthenticationRequired):
            resolve_or_provision_user(claims(sub=""))

    def test_an_unconnected_account_holding_the_email_is_explained(self):
        """An email column match with no *verified* EmailAddress row cannot be
        trusted, and creating a second user would violate the unique email."""
        User.objects.create_user(
            username="mona", email="mona@example.com", password="x"
        )

        with self.assertRaises(AuthenticationRequired) as ctx:
            resolve_or_provision_user(claims())

        self.assertIn("not connected to GitHub", str(ctx.exception))


class PrivateProfileFallbackTests(TestCase):
    """GitHub omits `email` from /user whenever the profile address is
    private, and GitHubProvider does not fetch /user/emails itself."""

    def test_falls_back_to_the_primary_verified_address(self):
        response = mock.Mock(
            status_code=200,
            json=lambda: [
                {"email": "old@example.com", "verified": True, "primary": False},
                {"email": "mona@example.com", "verified": True, "primary": True},
                {"email": "spam@example.com", "verified": False, "primary": False},
            ],
        )

        with mock.patch("mcp_server.auth.httpx2.get", return_value=response):
            user = resolve_or_provision_user(
                claims(email=None, access_token="gho_x")
            )

        self.assertEqual(user.email, "mona@example.com")

    def test_unverified_addresses_are_never_used(self):
        response = mock.Mock(
            status_code=200,
            json=lambda: [{"email": "spam@example.com", "verified": False}],
        )

        with mock.patch("mcp_server.auth.httpx2.get", return_value=response):
            with self.assertRaises(AuthenticationRequired):
                resolve_or_provision_user(claims(email=None, access_token="gho_x"))

    def test_a_github_outage_refuses_rather_than_provisioning_blind(self):
        with mock.patch("mcp_server.auth.httpx2.get", side_effect=OSError("boom")):
            with self.assertRaises(AuthenticationRequired):
                resolve_or_provision_user(claims(email=None, access_token="gho_x"))


class ClaimsFromTokenTests(TestCase):
    def test_reads_the_fields_GitHubProvider_sets(self):
        token = mock.Mock(
            claims={"sub": "7", "login": "octocat", "name": "Mona", "email": "m@x.test"},
            subject="7",
            token="gho_secret",
        )

        self.assertEqual(
            _claims_from_token(token),
            {
                "sub": "7",
                "login": "octocat",
                "name": "Mona",
                "email": "m@x.test",
                "access_token": "gho_secret",
            },
        )

    def test_falls_back_to_subject_when_the_sub_claim_is_absent(self):
        token = mock.Mock(claims={}, subject="9", token=None)

        self.assertEqual(_claims_from_token(token)["sub"], "9")


class AuthProviderTests(TestCase):
    @override_settings(MCP_GITHUB_CLIENT_ID="", MCP_GITHUB_CLIENT_SECRET="")
    def test_no_credentials_means_no_provider(self):
        self.assertIsNone(make_auth_provider())

    @override_settings(MCP_GITHUB_CLIENT_ID="id", MCP_GITHUB_CLIENT_SECRET="")
    def test_half_configured_credentials_are_treated_as_unconfigured(self):
        self.assertIsNone(make_auth_provider())

    @override_settings(
        MCP_AUTH_DISABLED=True,
        MCP_GITHUB_CLIENT_ID="id",
        MCP_GITHUB_CLIENT_SECRET="secret",
    )
    def test_auth_disabled_overrides_configured_credentials(self):
        self.assertIsNone(make_auth_provider())
