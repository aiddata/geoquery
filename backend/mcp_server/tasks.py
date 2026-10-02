from celery import shared_task
from django.utils import timezone

from .models import OAuthState


@shared_task(ignore_result=True)
def purge_expired_oauth_state():
    """Delete the MCP server's expired OAuth state.

    The store behind the OAuth proxy treats an expired row as missing but
    never deletes it, so every finished sign-in would otherwise leave its
    transaction and code rows behind, and every lapsed token its own.
    Client registrations carry no expiry and are kept.
    """
    deleted, _ = OAuthState.objects.filter(expires_at__lt=timezone.now()).delete()
    return {"deleted": deleted}
