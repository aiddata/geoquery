"""Serve the MCP server over streamable HTTP.

Separate from `runserver` because it is a separate process with a separate
lifecycle -- see the `mcp` service in docker-compose.yml. The same command runs
in production; only the environment differs.
"""

import uvicorn
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run the GeoQuery MCP server (streamable HTTP)."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=8001)
        parser.add_argument("--path", default="/mcp", help="MCP endpoint path.")
        parser.add_argument(
            "--allow-anonymous",
            action="store_true",
            help=(
                "Run with no authentication. Only permitted with DEBUG on and "
                "no GitHub OAuth app configured."
            ),
        )

    def handle(self, *args, **options):
        from mcp_server.auth import make_auth_provider
        from mcp_server.server import build_server

        auth = make_auth_provider()
        if auth is None:
            # Refusing here rather than warning: an unauthenticated MCP server
            # serves every caller as anonymous, which silently downgrades
            # catalog-restricted data to public and makes exports impossible.
            # That is a reasonable local default and never a production one.
            if not settings.DEBUG:
                raise CommandError(
                    "MCP_GITHUB_CLIENT_ID / MCP_GITHUB_CLIENT_SECRET are not "
                    "set, so the server would run unauthenticated. Configure "
                    "the GitHub OAuth app, or run with DEBUG on for local "
                    "development."
                )
            self.stdout.write(
                self.style.WARNING(
                    "No GitHub OAuth app configured: running UNAUTHENTICATED. "
                    "Every caller is anonymous — public data only, no exports."
                )
            )

        mcp = build_server(
            auth=auth,
            # With no auth provider there is no token to resolve, so every call
            # is anonymous rather than an error.
            user_resolver=(lambda: None) if auth is None else None,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"GeoQuery MCP on http://{options['host']}:{options['port']}"
                f"{options['path']} (base URL {settings.MCP_BASE_URL})"
            )
        )

        # stateless_http: each request stands alone, so the service can be
        # restarted or scaled without clients losing a session.
        uvicorn.run(
            mcp.http_app(path=options["path"], stateless_http=True),
            host=options["host"],
            port=options["port"],
            log_level="info",
        )
