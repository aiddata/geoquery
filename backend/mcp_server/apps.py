from django.apps import AppConfig


class McpServerConfig(AppConfig):
    """The MCP server.

    A second front end onto the same database as the Django REST API, served by
    its own process (``manage.py run_mcp``). Its one model is the OAuth state
    its replicas share; everything else it reads belongs to other apps. It is
    listed in INSTALLED_APPS so its model, management commands, tasks and
    tests are discovered, and so tool code can rely on the app registry being
    populated.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "mcp_server"
    verbose_name = "MCP server"
