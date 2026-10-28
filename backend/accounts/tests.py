from unittest import mock

from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed, user_signed_up
from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.adapter import SocialAccountAdapter
from accounts.claims import claim_requests_for_email, claim_requests_for_user
from accounts.features import BETA_FEATURES, CUSTOM_BOUNDARIES, has_feature
from analytics.models import Request

User = get_user_model()


def make_user(username, email):
    user = User.objects.create_user(username=username, email=email)
    return user


class ClaimHelperTests(TestCase):
    def setUp(self):
        self.user = make_user("alice", "alice@example.com")

    def test_claims_matching_requests_case_insensitively(self):
        r1 = Request.objects.create(contact="Alice@Example.com", status=1)
        r2 = Request.objects.create(contact="alice@example.com", status=1)
        other = Request.objects.create(contact="bob@example.com", status=1)

        claimed = claim_requests_for_email(self.user, "alice@example.com")

        self.assertEqual(claimed, 2)
        r1.refresh_from_db()
        r2.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(r1.user, self.user)
        self.assertEqual(r2.user, self.user)
        self.assertIsNone(other.user)

    def test_does_not_reclaim_owned_requests(self):
        other_user = make_user("bob", "bob@example.com")
        r = Request.objects.create(
            contact="alice@example.com", status=1, user=other_user
        )

        claimed = claim_requests_for_email(self.user, "alice@example.com")

        self.assertEqual(claimed, 0)
        r.refresh_from_db()
        self.assertEqual(r.user, other_user)

    def test_blank_email_claims_nothing(self):
        Request.objects.create(contact="alice@example.com", status=1)
        self.assertEqual(claim_requests_for_email(self.user, ""), 0)
        self.assertEqual(claim_requests_for_email(self.user, None), 0)

    def test_claim_for_user_sweeps_only_verified_emails(self):
        EmailAddress.objects.create(
            user=self.user, email="alice@example.com", verified=True, primary=True
        )
        EmailAddress.objects.create(
            user=self.user, email="old@example.com", verified=False
        )
        verified_req = Request.objects.create(contact="alice@example.com", status=1)
        unverified_req = Request.objects.create(contact="old@example.com", status=1)

        claimed = claim_requests_for_user(self.user)

        self.assertEqual(claimed, 1)
        verified_req.refresh_from_db()
        unverified_req.refresh_from_db()
        self.assertEqual(verified_req.user, self.user)
        self.assertIsNone(unverified_req.user)


class ClaimSignalTests(TestCase):
    def setUp(self):
        self.user = make_user("alice", "alice@example.com")

    def test_email_confirmed_triggers_claim(self):
        email_address = EmailAddress.objects.create(
            user=self.user, email="old@example.com", verified=True
        )
        req = Request.objects.create(contact="Old@Example.com", status=1)

        email_confirmed.send(
            sender=EmailAddress, request=None, email_address=email_address
        )

        req.refresh_from_db()
        self.assertEqual(req.user, self.user)

    def test_user_signed_up_claims_provider_verified_emails(self):
        EmailAddress.objects.create(
            user=self.user, email="alice@example.com", verified=True, primary=True
        )
        req = Request.objects.create(contact="alice@example.com", status=1)

        user_signed_up.send(sender=User, request=None, user=self.user)

        req.refresh_from_db()
        self.assertEqual(req.user, self.user)


class MyRequestsViewTests(TestCase):
    def setUp(self):
        self.user = make_user("alice", "alice@example.com")
        EmailAddress.objects.create(
            user=self.user, email="alice@example.com", verified=True, primary=True
        )
        self.url = reverse("my-requests")

    def test_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (401, 403))

    def test_returns_union_of_claimed_and_email_matched(self):
        claimed = Request.objects.create(
            contact="typo@example.com", status=1, user=self.user
        )
        matched = Request.objects.create(contact="ALICE@example.com", status=1)
        Request.objects.create(contact="bob@example.com", status=1)

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()}
        self.assertEqual(ids, {str(claimed.id), str(matched.id)})

    def test_unverified_email_does_not_match(self):
        EmailAddress.objects.create(
            user=self.user, email="unverified@example.com", verified=False
        )
        Request.objects.create(contact="unverified@example.com", status=1)

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])



class GitHubSignupEmailTests(TestCase):
    """GitHub signup stores only the addresses the user chose."""

    signup_url = "/api/_allauth/browser/v1/auth/provider/signup"

    def sociallogin(self, *addresses, profile_email=""):
        """A GitHub login carrying ``(email, verified, primary)`` addresses."""
        return SocialLogin(
            user=User(email=profile_email),
            account=SocialAccount(provider="github", uid="12345", extra_data={}),
            email_addresses=[
                EmailAddress(email=email, verified=verified, primary=primary)
                for email, verified, primary in addresses
            ],
            provider=get_social_adapter().get_provider(None, "github"),
        )

    def request(self):
        request = RequestFactory().get("/")
        SessionMiddleware(lambda request: None).process_request(request)
        return request

    def start_pending_signup(self, sociallogin):
        session = self.client.session
        session["socialaccount_sociallogin"] = sociallogin.serialize()
        session.save()

    def stored_emails(self):
        user = User.objects.get()
        return {
            address.email: (address.verified, address.primary)
            for address in EmailAddress.objects.filter(user=user)
        }

    def test_drops_noreply_and_unverified_addresses(self):
        sociallogin = self.sociallogin(
            ("alice@example.com", True, True),
            ("12345+alice@users.noreply.github.com", True, False),
            ("unconfirmed@example.com", False, False),
        )

        SocialAccountAdapter().pre_social_login(self.request(), sociallogin)

        self.assertEqual(
            [address.email for address in sociallogin.email_addresses],
            ["alice@example.com"],
        )

    def test_auto_signup_only_with_a_single_address(self):
        adapter = SocialAccountAdapter()
        one = self.sociallogin(("alice@example.com", True, True))
        two = self.sociallogin(
            ("alice@example.com", True, True), ("work@example.org", True, False)
        )

        self.assertTrue(adapter.is_auto_signup_allowed(self.request(), one))
        self.assertFalse(adapter.is_auto_signup_allowed(self.request(), two))

    def test_pending_signup_offers_filtered_addresses(self):
        sociallogin = self.sociallogin(
            ("alice@example.com", True, True),
            ("work@example.org", True, False),
            ("12345+alice@users.noreply.github.com", True, False),
        )
        SocialAccountAdapter().pre_social_login(self.request(), sociallogin)
        self.start_pending_signup(sociallogin)

        response = self.client.get(self.signup_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["email"] for item in response.json()["data"]["email"]],
            ["alice@example.com", "work@example.org"],
        )

    def test_signup_stores_only_selected_addresses(self):
        kept = Request.objects.create(contact="work@example.org", status=1)
        skipped = Request.objects.create(contact="private@example.net", status=1)
        self.start_pending_signup(
            self.sociallogin(
                ("alice@example.com", True, True),
                ("work@example.org", True, False),
                ("private@example.net", True, False),
            )
        )

        response = self.client.post(
            self.signup_url,
            {"email": "work@example.org", "emails": ["alice@example.com"]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.stored_emails(),
            {"work@example.org": (True, True), "alice@example.com": (True, False)},
        )
        self.assertEqual(User.objects.get().email, "work@example.org")
        kept.refresh_from_db()
        skipped.refresh_from_db()
        self.assertEqual(kept.user, User.objects.get())
        self.assertIsNone(skipped.user)

    def test_signup_rejects_addresses_github_did_not_offer(self):
        self.start_pending_signup(
            self.sociallogin(
                ("alice@example.com", True, True), ("work@example.org", True, False)
            )
        )

        response = self.client.post(
            self.signup_url,
            {"email": "alice@example.com", "emails": ["someone@example.net"]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_typed_address_needs_verification(self):
        self.start_pending_signup(
            self.sociallogin(
                ("alice@example.com", True, True), ("work@example.org", True, False)
            )
        )

        self.client.post(
            self.signup_url,
            {"email": "other@example.net"},
            content_type="application/json",
        )

        self.assertEqual(self.stored_emails(), {"other@example.net": (False, True)})

    def test_auto_signup_ignores_filtered_profile_email(self):
        sociallogin = self.sociallogin(
            ("alice@example.com", True, True),
            profile_email="12345+alice@users.noreply.github.com",
        )
        request = self.request()
        adapter = SocialAccountAdapter()
        adapter.pre_social_login(request, sociallogin)

        user = adapter.save_user(request, sociallogin)

        self.assertEqual(user.email, "alice@example.com")
        self.assertEqual(self.stored_emails(), {"alice@example.com": (True, True)})


class BetaTesterFlagTests(TestCase):
    url = "/api/_allauth/browser/v1/auth/session"

    def flag(self, user):
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["user"]["is_beta_tester"]

    def test_false_without_permission(self):
        self.assertIs(self.flag(make_user("alice", "alice@example.com")), False)

    def test_true_with_permission(self):
        user = make_user("bob", "bob@example.com")
        user.user_permissions.add(Permission.objects.get(codename="beta_tester"))

        self.assertIs(self.flag(user), True)

    def test_true_via_group(self):
        user = make_user("carol", "carol@example.com")
        group = Group.objects.create(name="Beta testers")
        group.permissions.add(Permission.objects.get(codename="beta_tester"))
        user.groups.add(group)

        self.assertIs(self.flag(user), True)

    def test_true_for_superuser(self):
        user = User.objects.create_superuser(
            username="root", email="root@example.com", password="x"
        )

        self.assertIs(self.flag(user), True)


class HasFeatureTests(TestCase):
    def test_beta_feature_requires_beta_tester(self):
        user = make_user("alice", "alice@example.com")
        self.assertFalse(has_feature(None, CUSTOM_BOUNDARIES))
        self.assertFalse(has_feature(AnonymousUser(), CUSTOM_BOUNDARIES))
        self.assertFalse(has_feature(user, CUSTOM_BOUNDARIES))

        user.user_permissions.add(Permission.objects.get(codename="beta_tester"))
        user = User.objects.get(pk=user.pk)  # drop the cached permission set
        self.assertTrue(has_feature(user, CUSTOM_BOUNDARIES))

    def test_released_feature_is_open_to_everyone(self):
        with mock.patch("accounts.features.BETA_FEATURES", frozenset()):
            self.assertTrue(has_feature(None, CUSTOM_BOUNDARIES))
            self.assertTrue(has_feature(AnonymousUser(), CUSTOM_BOUNDARIES))

    def test_config_lists_beta_features(self):
        response = self.client.get("/api/config/")

        self.assertEqual(response.json()["beta_features"], sorted(BETA_FEATURES))
