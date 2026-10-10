"""Attach historical requests to user accounts by verified email.

Requests predating the account system (and anonymous submissions) are keyed
only by the ``contact`` email string -- both in ``Request`` and in
``LegacyRequest``, the imported archive from the previous version of GeoQuery.
When a user proves ownership of an email address (allauth verification, or a
provider-verified email at social signup), every unclaimed request under that
address in either table becomes theirs.
"""


def claim_requests_for_email(user, email: str) -> int:
    """Claim all unclaimed requests whose contact matches this verified email.

    Covers both current requests and the imported legacy ones: a user proving
    ownership of an address should get their whole history, not the half of it
    that postdates the rewrite.

    Only rows with no owner are taken, so claims are permanent: removing the
    email from the account later does not release them. Two accounts can never
    race for the same address because allauth enforces unique verified emails
    (ACCOUNT_UNIQUE_EMAIL).

    Returns the total number of requests claimed across both tables.
    """
    from analytics.models import LegacyRequest, Request

    email = (email or "").strip()
    if not email:
        return 0

    claimed = Request.objects.filter(
        contact__iexact=email, user__isnull=True
    ).update(user=user)
    claimed += LegacyRequest.objects.filter(
        contact__iexact=email, user__isnull=True
    ).update(user=user)
    return claimed


def claim_requests_for_user(user) -> int:
    """Run the claim sweep for every verified email on the account."""
    from allauth.account.models import EmailAddress

    claimed = 0
    for email in EmailAddress.objects.filter(user=user, verified=True).values_list(
        "email", flat=True
    ):
        claimed += claim_requests_for_email(user, email)
    return claimed
