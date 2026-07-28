from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed, user_signed_up
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.claims import claim_requests_for_email, claim_requests_for_user
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
