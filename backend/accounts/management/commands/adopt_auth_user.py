"""Convert a pre-accounts database so `migrate` can run against it.

Databases first migrated under the default AUTH_USER_MODEL carry an applied
admin.0001_initial whose *swappable* dependency now resolves to
accounts.0001_initial, which was never applied. Every `migrate` then dies in
MigrationLoader.check_consistent_history() before any migration is loaded:

    InconsistentMigrationHistory: Migration admin.0001_initial is applied
    before its dependency accounts.0001_initial

That check is the first statement in migrate's handle(), ahead of the pre_migrate
signal and ahead of the plan, and it runs even under --fake -- so no migration,
and no hook inside the migration framework, can repair it. It has to happen
before `migrate` is called at all, which is what this command is for.

The DDL lives in accounts/sql/adopt_auth_user.sql. This command decides whether
that DDL needs to run; the SQL keeps its own independent preconditions.

Safe to run unconditionally on every deploy: on an already-converted database,
and on a fresh one that never had a legacy user table, it reports and exits 0.
It is also safe to run concurrently -- an advisory lock serialises replicas, and
whichever loses the race finds the work already done.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections, transaction

SQL_PATH = Path(__file__).resolve().parent.parent.parent / "sql" / "adopt_auth_user.sql"

# Arbitrary constant, unique to this operation. Held for the duration of the
# transaction so two replicas running `migrate` at once cannot both convert.
ADVISORY_LOCK_ID = 8419307742115

NOTHING_TO_DO = "nothing-to-do"
ADOPTED = "adopted"


class Command(BaseCommand):
    help = (
        "Adopt a legacy auth_user table as accounts.User so that migrate can "
        "run. No-op on databases that do not need it. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default=DEFAULT_DB_ALIAS,
            help="Database to convert. Defaults to the default alias.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report whether conversion is needed without writing.",
        )

    def handle(self, *args, **options):
        alias = options["database"]
        dry_run = options["dry_run"]
        verbosity = options["verbosity"]
        connection = connections[alias]

        if connection.vendor != "postgresql":
            raise CommandError(
                f"Database {alias!r} is {connection.vendor}, but this conversion "
                f"is PostgreSQL-specific."
            )

        try:
            sql = SQL_PATH.read_text()
        except OSError as exc:
            raise CommandError(f"Cannot read {SQL_PATH}: {exc}") from exc

        with transaction.atomic(using=alias), connection.cursor() as cursor:
            # Taken inside the transaction and before the state is read, so the
            # answer cannot go stale between the check and the conversion.
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ADVISORY_LOCK_ID])

            status, detail = self._inspect(cursor)
            if status is NOTHING_TO_DO:
                # Stay quiet on the common path. This runs before every migrate,
                # including every test-database build, and "nothing to do" is not
                # news -- but it is the answer when it was asked for explicitly.
                if dry_run or verbosity >= 2:
                    self.stdout.write(f"accounts.User adoption not needed: {detail}")
                return

            if dry_run:
                if verbosity >= 1:
                    self.stdout.write(
                        self.style.WARNING(f"would adopt legacy auth_user: {detail}")
                    )
                # Roll back rather than commit a transaction that did nothing but
                # take a lock.
                transaction.set_rollback(True, using=alias)
                return

            if verbosity >= 1:
                self.stdout.write(f"adopting legacy auth_user: {detail}")
            cursor.execute(sql)

        if verbosity >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    "adopted auth_user as accounts_user and recorded "
                    "accounts.0001_initial; migrate can now run."
                )
            )

    def _inspect(self, cursor):
        """Decide whether the legacy user table still needs adopting."""
        cursor.execute(
            """
            SELECT to_regclass('public.auth_user')     IS NOT NULL,
                   to_regclass('public.accounts_user') IS NOT NULL,
                   to_regclass('public.django_migrations') IS NOT NULL
            """
        )
        has_auth_user, has_accounts_user, has_migrations = cursor.fetchone()

        if has_accounts_user:
            return NOTHING_TO_DO, "accounts_user already exists"
        if not has_migrations:
            # Nothing has ever been migrated here; `migrate` will build the
            # accounts app from scratch, which is the outcome we want anyway.
            return NOTHING_TO_DO, "empty database"
        if not has_auth_user:
            return NOTHING_TO_DO, "no legacy auth_user table"

        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM django_migrations "
            "WHERE app = 'accounts' AND name = '0001_initial')"
        )
        if cursor.fetchone()[0]:
            # Recorded as applied but the table is missing -- refuse rather than
            # run DDL whose preconditions clearly do not describe this database.
            raise CommandError(
                "accounts.0001_initial is recorded as applied but accounts_user "
                "does not exist. Inspect this database by hand."
            )

        cursor.execute("SELECT count(*) FROM auth_user")
        return ADOPTED, f"{cursor.fetchone()[0]} user(s) to carry over"
