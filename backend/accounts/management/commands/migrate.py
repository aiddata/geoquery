"""`migrate`, preceded by the legacy user-table adoption.

Django resolves management commands from INSTALLED_APPS before django.core, so
this shadows the built-in `migrate` and every existing caller -- deploy jobs,
entrypoints, the test runner -- picks it up with no change.

The adoption cannot live in a migration, or in any hook the migration framework
offers: check_consistent_history() is the first statement in migrate's handle(),
so on an unconverted database `migrate` fails before pre_migrate fires or a plan
is built. Running it here is the last point that is still early enough.

`adopt_auth_user` is a no-op on databases that do not need it, so this adds one
cheap query to every other migrate.
"""

from django.core.management import call_command
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import DEFAULT_DB_ALIAS


class Command(MigrateCommand):
    def handle(self, *args, **options):
        # --database is the only option worth forwarding; the rest describe how
        # to migrate, which the adoption has no opinion about.
        call_command(
            "adopt_auth_user",
            database=options.get("database", DEFAULT_DB_ALIAS),
            verbosity=options.get("verbosity", 1),
        )
        return super().handle(*args, **options)
