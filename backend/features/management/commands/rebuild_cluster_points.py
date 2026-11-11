from django.core.management.base import BaseCommand

from features.matviews import rebuild_cluster_points


class Command(BaseCommand):
    help = (
        "Rebuild every collection's map clusters (features_cluster_points) from "
        "features_points, after a change to features.clusters. Leaves the "
        "simplified-geometry tables alone; all of production takes seconds."
    )

    def handle(self, *args, **options):
        rebuild_cluster_points()
        self.stdout.write(self.style.SUCCESS("Cluster points rebuilt."))
