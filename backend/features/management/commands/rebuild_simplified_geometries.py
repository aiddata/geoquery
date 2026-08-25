from django.core.management.base import BaseCommand

from features.matviews import rebuild_simplified_geometries


class Command(BaseCommand):
    help = (
        "Rebuild all simplified-geometry tables from source features, one "
        "collection at a time (row locks only; never blocks tile readers)"
    )

    def handle(self, *args, **options):
        self.stdout.write("Rebuilding simplified-geometry tables...")
        rebuild_simplified_geometries()
        self.stdout.write(self.style.SUCCESS("All simplified-geometry tables rebuilt."))
