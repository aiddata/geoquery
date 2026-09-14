from django.apps import AppConfig


class McpServerConfig(AppConfig):
    """The MCP server.

    Holds no models -- it is a second front end onto the same database as the
    Django REST API, served by its own process (``manage.py run_mcp``). It is
    listed in INSTALLED_APPS so its management commands and tests are
    discovered, and so tool code can rely on the app registry being populated.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "mcp_server"
    verbose_name = "MCP server"
