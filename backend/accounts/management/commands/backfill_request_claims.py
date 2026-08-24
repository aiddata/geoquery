from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand

from accounts.claims import claim_requests_for_email
from analytics.models import Request


class Command(BaseCommand):
    help = (
        "Attach unclaimed historical requests to accounts by matching "
        "Request.contact against every verified email address. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be claimed without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        total = 0
        qs = EmailAddress.objects.filter(verified=True).select_related("user")
        for email_address in qs.iterator():
            if dry_run:
                count = Request.objects.filter(
                    contact__iexact=email_address.email, user__isnull=True
                ).count()
            else:
                count = claim_requests_for_email(
                    email_address.user, email_address.email
                )
            if count:
                self.stdout.write(
                    f"{email_address.email} -> {email_address.user} : {count} request(s)"
                )
            total += count

        verb = "would be claimed" if dry_run else "claimed"
        self.stdout.write(self.style.SUCCESS(f"{total} request(s) {verb}."))
