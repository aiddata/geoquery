"""Give adopted legacy accounts the allauth EmailAddress rows they lack.

Users carried over by ``accounts/sql/adopt_auth_user.sql`` predate allauth, so
they have a ``User.email`` but no ``account_emailaddress`` row. That gap is not
cosmetic:

- ACCOUNT_LOGIN_METHODS is {"email"}, and allauth authenticates by looking up an
  EmailAddress -- so without one the account cannot log in at all.
- SOCIALACCOUNT_EMAIL_AUTHENTICATION matches a GitHub login against verified
  EmailAddress rows. With no row to match, allauth falls through to signup and
  hits the unique constraint on User.email instead of connecting the accounts.

Run once after `migrate`. Safe to re-run: existing rows are left alone.
"""

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.claims import claim_requests_for_user


class Command(BaseCommand):
    help = (
        "Create verified allauth EmailAddress rows for pre-allauth users that "
        "have none, so they can log in and match social accounts. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing.",
        )
        parser.add_argument(
            "--unverified",
            action="store_true",
            help=(
                "Create the addresses as unverified. Users must then complete "
                "email confirmation before they can log in, and a GitHub login "
                "on the same address will not auto-connect. Safer if you do not "
                "trust every address already in the user table."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        verified = not options["unverified"]

        User = get_user_model()
        # Addresses are lowercased by allauth.account.0006_emailaddress_lower,
        # so User.email is already normalised by the time this runs.
        candidates = (
            User.objects.exclude(email="")
            .exclude(emailaddress__isnull=False)
            .order_by("pk")
        )

        created = skipped = claimed = 0
        for user in candidates.iterator():
            # An address already attached to a *different* account means these
            # two rows disagree about who owns it. Report rather than guess.
            clash = EmailAddress.objects.filter(email__iexact=user.email).first()
            if clash is not None:
                self.stderr.write(
                    self.style.WARNING(
                        f"skipped {user} <{user.email}>: address already belongs "
                        f"to {clash.user}"
                    )
                )
                skipped += 1
                continue

            if not dry_run:
                with transaction.atomic():
                    EmailAddress.objects.create(
                        user=user,
                        email=user.email,
                        verified=verified,
                        primary=True,
                    )
                    # Mirrors the user_signed_up/email_confirmed receivers in
                    # accounts.signals, which never fire for adopted users.
                    if verified:
                        claimed += claim_requests_for_user(user)
            created += 1
            self.stdout.write(f"{user} <{user.email}>")

        blank = User.objects.filter(email="").count()
        if blank:
            self.stderr.write(
                self.style.WARNING(
                    f"{blank} user(s) have a blank email and were skipped; they "
                    f"cannot log in until an address is set."
                )
            )

        verb = "would create" if dry_run else "created"
        state = "verified" if verified else "unverified"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {created} {state} address(es), skipped {skipped}"
                + (f", claimed {claimed} request(s)" if not dry_run else "")
            )
        )
