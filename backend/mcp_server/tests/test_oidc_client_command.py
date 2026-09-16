"""Registering the MCP server's OIDC client.

A deployment runs this on every install and upgrade, so it has to be safe to
repeat. The redirect URI it writes is the one value the whole handshake turns
on: the provider matches it exactly against what the MCP server sends, and
both derive it from ``MCP_BASE_URL``.
"""

from io import StringIO

from allauth.idp.oidc.models import Client
from django.core.management import call_command
from django.test import TestCase, override_settings

CLIENT_ID = "geoquery-mcp"
SECRET = "s3cret-value"


@override_settings(
    MCP_OIDC_CLIENT_ID=CLIENT_ID,
    MCP_OIDC_CLIENT_SECRET=SECRET,
    MCP_BASE_URL="https://mcp.geoquery.org",
)
class EnsureMcpOidcClientTests(TestCase):
    def run_command(self):
        out = StringIO()
        call_command("ensure_mcp_oidc_client", stdout=out)
        return out.getvalue()

    def test_creates_the_client(self):
        self.run_command()
        client = Client.objects.get(pk=CLIENT_ID)
        self.assertEqual(client.type, Client.Type.CONFIDENTIAL)
        self.assertEqual(
            client.get_redirect_uris(), ["https://mcp.geoquery.org/auth/callback"]
        )
        self.assertEqual(client.get_response_types(), ["code"])
        self.assertEqual(
            client.get_grant_types(), ["authorization_code", "refresh_token"]
        )
        self.assertEqual(client.get_scopes(), ["openid"])

    def test_the_secret_is_stored_hashed_and_verifies(self):
        self.run_command()
        client = Client.objects.get(pk=CLIENT_ID)
        self.assertNotEqual(client.secret, SECRET)
        self.assertTrue(client.check_secret(SECRET))

    def test_is_idempotent(self):
        self.run_command()
        first = Client.objects.get(pk=CLIENT_ID).secret

        self.run_command()

        self.assertEqual(Client.objects.count(), 1)
        client = Client.objects.get(pk=CLIENT_ID)
        self.assertTrue(client.check_secret(SECRET))
        # The hash is salted, so re-hashing on every deploy would rewrite the
        # column even when nothing changed.
        self.assertEqual(client.secret, first)

    def test_a_rotated_secret_is_written(self):
        self.run_command()
        with override_settings(MCP_OIDC_CLIENT_SECRET="rotated"):
            self.run_command()
        client = Client.objects.get(pk=CLIENT_ID)
        self.assertTrue(client.check_secret("rotated"))
        self.assertFalse(client.check_secret(SECRET))

    def test_a_moved_base_url_moves_the_redirect_uri(self):
        self.run_command()
        with override_settings(MCP_BASE_URL="https://geoquery.org/"):
            self.run_command()
        client = Client.objects.get(pk=CLIENT_ID)
        self.assertEqual(
            client.get_redirect_uris(), ["https://geoquery.org/auth/callback"]
        )

    @override_settings(MCP_OIDC_CLIENT_ID="", MCP_OIDC_CLIENT_SECRET="")
    def test_skips_quietly_when_the_mcp_server_is_not_configured(self):
        # The same deployment step runs where the MCP server is switched off;
        # it must not fail the upgrade.
        output = self.run_command()
        self.assertEqual(Client.objects.count(), 0)
        self.assertIn("skipping", output)
