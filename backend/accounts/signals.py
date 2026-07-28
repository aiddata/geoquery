"""Signal handlers that auto-claim historical requests.

Three triggers cover the ways an email becomes verifiably owned:

- ``email_confirmed``: a (possibly secondary) address verified via the emailed
  key — the explicit "claim my old requests" path.
- ``user_signed_up``: GitHub-verified emails arrive as
  ``EmailAddress(verified=True)`` without ever firing ``email_confirmed``.
- ``user_logged_in``: idempotent sweep so requests submitted anonymously under
  an already-verified address get picked up next session. Cheap thanks to the
  functional index on LOWER(requests.contact).
"""

from allauth.account.signals import email_confirmed, user_logged_in, user_signed_up
from django.dispatch import receiver

from .claims import claim_requests_for_email, claim_requests_for_user


@receiver(email_confirmed)
def claim_on_email_confirmed(sender, request, email_address, **kwargs):
    claim_requests_for_email(email_address.user, email_address.email)


@receiver(user_signed_up)
def claim_on_signup(sender, request, user, **kwargs):
    claim_requests_for_user(user)


@receiver(user_logged_in)
def claim_on_login(sender, request, user, **kwargs):
    claim_requests_for_user(user)
