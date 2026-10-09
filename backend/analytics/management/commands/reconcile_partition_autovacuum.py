from django.core.management.base import BaseCommand

from analytics.partition_vacuum import reconcile_partition_autovacuum


class Command(BaseCommand):
    help = (
        "Put each extract_tasks partition on its autovacuum profile: active "
        "while it has pending or running tasks, drained once it has none. "
        "The beat task does this every ten minutes; this runs it on demand."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without altering anything",
        )

    def handle(self, *args, **options):
        result = reconcile_partition_autovacuum(dry_run=options["dry_run"])
        verb = "would set" if options["dry_run"] else "set"
        for partition, profile in result.pop("changes"):
            self.stdout.write(f"{partition}: {verb} {profile}")
        self.stdout.write(
            ", ".join(f"{k}={v}" for k, v in result.items())
        )
