"""Attach historical requests to user accounts by verified email.

Requests predating the account system (and anonymous submissions) are keyed
only by the ``Request.contact`` email string. When a user proves ownership of
an email address (allauth verification, or a provider-verified email at social
signup), every unclaimed request under that address becomes theirs.
"""


def claim_requests_for_email(user, email: str) -> int:
    """Claim all unclaimed requests whose contact matches this verified email.

    Only rows with no owner are taken, so claims are permanent: removing the
    email from the account later does not release them. Two accounts can never
    race for the same address because allauth enforces unique verified emails
    (ACCOUNT_UNIQUE_EMAIL).

    Returns the number of requests claimed.
    """
    from analytics.models import Request

    email = (email or "").strip()
    if not email:
        return 0
    return Request.objects.filter(contact__iexact=email, user__isnull=True).update(
        user=user
    )


def claim_requests_for_user(user) -> int:
    """Run the claim sweep for every verified email on the account."""
    from allauth.account.models import EmailAddress

    claimed = 0
    for email in EmailAddress.objects.filter(user=user, verified=True).values_list(
        "email", flat=True
    ):
        claimed += claim_requests_for_email(user, email)
    return claimed
