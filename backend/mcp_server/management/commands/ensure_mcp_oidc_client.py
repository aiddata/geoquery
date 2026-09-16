"""Register the MCP server as a client of GeoQuery's OIDC provider.

Idempotent, and meant to run on every install and upgrade alongside
``migrate`` -- a deployment hands the same ``MCP_BASE_URL``,
``MCP_OIDC_CLIENT_ID`` and ``MCP_OIDC_CLIENT_SECRET`` to this command, to the
backend and to the MCP server, so the registered redirect URI and the one the
MCP server builds for itself cannot drift apart.

It deliberately needs nothing beyond those three values and a database: the
Job that runs it has no signing key, no results directory and no broker.
"""

from allauth.idp.oidc.models import Client
from django.conf import settings
from django.core.management.base import BaseCommand

CLIENT_NAME = "GeoQuery MCP server"

# openid is all the MCP server needs: it resolves the caller from the
# token's `sub` claim and reads everything else (name, email) from the
# account itself, so it never asks for the email or profile scopes. No scope
# grants data access -- that comes from the catalog grants on the resolved
# account. Keep in step with mcp_server.auth.SCOPES.
SCOPES = ["openid"]
GRANT_TYPES = ["authorization_code", "refresh_token"]
RESPONSE_TYPES = ["code"]


class Command(BaseCommand):
    help = "Create or update the MCP server's OIDC client registration."

    def handle(self, *args, **options) -> None:
        client_id = settings.MCP_OIDC_CLIENT_ID
        client_secret = settings.MCP_OIDC_CLIENT_SECRET

        # Not an error: the same Job runs on deployments with the MCP server
        # switched off, and should not fail them.
        if not (client_id and client_secret):
            self.stdout.write(
                "MCP_OIDC_CLIENT_ID / MCP_OIDC_CLIENT_SECRET are not set; "
                "skipping MCP OIDC client registration."
            )
            return

        redirect_uri = f"{settings.MCP_BASE_URL.rstrip('/')}/auth/callback"

        client = Client.objects.filter(pk=client_id).first()
        created = client is None
        if client is None:
            client = Client(id=client_id)

        client.name = CLIENT_NAME
        client.type = Client.Type.CONFIDENTIAL
        client.set_redirect_uris([redirect_uri])
        client.set_grant_types(GRANT_TYPES)
        client.set_response_types(RESPONSE_TYPES)
        client.set_scopes(SCOPES)
        client.set_default_scopes(SCOPES)
        # allauth renders the consent page; the MCP server's OAuth proxy does
        # not show one of its own.
        client.skip_consent = False

        # `secret` holds a salted hash, so re-hashing on every deploy would
        # rewrite the column each time even when nothing changed. Only set it
        # when the stored hash does not already match.
        if created or not client.check_secret(client_secret):
            client.set_secret(client_secret)

        client.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} OIDC client "
                f"{client_id!r} with redirect URI {redirect_uri}"
            )
        )
