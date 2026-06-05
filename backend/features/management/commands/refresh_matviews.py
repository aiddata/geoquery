from django.core.management.base import BaseCommand

from features.matviews import refresh_materialized_views


class Command(BaseCommand):
    help = "Refresh all simplified-geometry materialized views"

    def handle(self, *args, **options):
        self.stdout.write("Refreshing simplified-geometry materialized views...")
        refresh_materialized_views()
        self.stdout.write(self.style.SUCCESS("All materialized views refreshed."))
