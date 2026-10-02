"""State the MCP replicas share.

Running more than one MCP pod depends on two things no single pod can keep
to itself: the OAuth proxy's state (an /authorize on one replica, its
/auth/callback on another) and the key sealing ``submit_request``'s
confirmation round trip (the prompt from one replica, the answer to
another). These tests stand up two independent instances of each, as two
pods would, and check they agree.
"""

import asyncio
from datetime import timedelta
from unittest import mock

from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from mcp_server.auth import (
    _oauth_state_storage,
    make_auth_provider,
    make_request_state_security,
)
from mcp_server.models import OAuthState
from mcp_server.tasks import purge_expired_oauth_state

CONFIGURED = dict(
    MCP_OIDC_CLIENT_ID="geoquery-mcp",
    MCP_OIDC_CLIENT_SECRET="s3cret",
    MCP_AUTH_DISABLED=False,
    MCP_JWT_SIGNING_KEY="signing-key-" + "x" * 40,
)


def run_on_two_replicas(work):
    """Run ``work(a, b)`` with two separately built storages, then close them.

    Each storage owns its own asyncpg pool, so each has to be closed on the
    loop that opened it -- a pool left open would hold the test database.
    """

    async def go():
        a, b = _oauth_state_storage(), _oauth_state_storage()
        try:
            return await work(a, b)
        finally:
            await a.key_value.close()
            await b.key_value.close()

    return asyncio.run(go())


@override_settings(**CONFIGURED)
class OAuthStateStorageTests(TransactionTestCase):
    def test_one_replica_reads_what_another_wrote(self):
        async def work(a, b):
            await a.put(
                key="txn-1", value={"client_id": "abc"}, collection="mcp-oauth-transactions"
            )
            return await b.get(key="txn-1", collection="mcp-oauth-transactions")

        self.assertEqual(run_on_two_replicas(work), {"client_id": "abc"})

    def test_values_are_encrypted_at_rest(self):
        async def work(a, b):
            await a.put(
                key="tok", value={"access_token": "upstream-secret"}, collection="mcp-upstream-tokens"
            )

        run_on_two_replicas(work)
        row = OAuthState.objects.get(collection="mcp-upstream-tokens", key="tok")
        self.assertNotIn("upstream-secret", str(row.value))

    def test_an_expired_entry_reads_as_missing(self):
        async def work(a, b):
            await a.put(key="code", value={"c": 1}, collection="mcp-authorization-codes", ttl=0.05)
            await asyncio.sleep(0.1)
            return await b.get(key="code", collection="mcp-authorization-codes")

        self.assertIsNone(run_on_two_replicas(work))
        # ...but is still in the table, which is why the purge task exists.
        self.assertTrue(OAuthState.objects.filter(key="code").exists())


class PurgeExpiredOAuthStateTests(TestCase):
    def test_deletes_only_expired_rows(self):
        now = timezone.now()
        OAuthState.objects.create(
            collection="mcp-authorization-codes", key="old", value={},
            expires_at=now - timedelta(minutes=1),
        )
        OAuthState.objects.create(
            collection="mcp-authorization-codes", key="live", value={},
            expires_at=now + timedelta(minutes=5),
        )
        OAuthState.objects.create(
            collection="mcp-oauth-proxy-clients", key="client", value={},
            expires_at=None,
        )

        self.assertEqual(purge_expired_oauth_state(), {"deleted": 1})
        self.assertEqual(
            set(OAuthState.objects.values_list("key", flat=True)), {"live", "client"}
        )


class AuthProviderStorageTests(TestCase):
    @override_settings(**CONFIGURED)
    def test_the_proxy_keeps_its_state_in_the_shared_table(self):
        from key_value.aio.stores.postgresql import PostgreSQLStore
        from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

        with mock.patch("fastmcp.server.auth.oauth_proxy.OAuthProxy") as proxy:
            make_auth_provider()
        storage = proxy.call_args.kwargs["client_storage"]
        self.assertIsInstance(storage, FernetEncryptionWrapper)
        self.assertIsInstance(storage.key_value, PostgreSQLStore)
        self.assertEqual(storage.key_value._table_name, "mcp_oauth_state")
        # The migration makes the table; the store must not try to.
        self.assertFalse(storage.key_value._auto_create)


class RequestStateSecurityTests(TestCase):
    @override_settings(**CONFIGURED)
    def test_a_confirmation_sealed_on_one_replica_opens_on_another(self):
        sealed = make_request_state_security().codec.seal(b"expected-hash")
        self.assertEqual(
            make_request_state_security().codec.unseal(sealed), b"expected-hash"
        )

    @override_settings(**{**CONFIGURED, "MCP_AUTH_DISABLED": True})
    def test_unauthenticated_keeps_the_per_process_default(self):
        self.assertIsNone(make_request_state_security())
