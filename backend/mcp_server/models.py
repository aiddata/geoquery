from django.db import models


class OAuthState(models.Model):
    """FastMCP's OAuth proxy state, shared by every MCP replica.

    Client registrations, in-flight authorizations, codes and the upstream
    GeoQuery tokens each assistant holds. The proxy reads and writes this
    table itself through ``key_value``'s ``PostgreSQLStore`` (see
    ``mcp_server.auth``); the model exists so Django owns the schema and the
    purge task can use the ORM. The columns are that store's layout exactly,
    and every ``value`` is Fernet-encrypted before it gets here. The library
    calls that store unstable, which is why pyproject.toml caps it below 0.5:
    check its DDL against this model before raising the cap.

    The store only hides expired rows on read and never deletes them, so
    ``mcp_server.tasks.purge_expired_oauth_state`` does.
    """

    pk = models.CompositePrimaryKey("collection", "key")
    collection = models.TextField()
    key = models.TextField()
    value = models.JSONField()
    ttl = models.FloatField(null=True)
    created_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "mcp_oauth_state"
        indexes = [
            models.Index(
                fields=["expires_at"],
                name="mcp_oauth_state_expires_idx",
                condition=models.Q(expires_at__isnull=False),
            ),
        ]

    def __str__(self):
        return f"{self.collection}/{self.key}"
