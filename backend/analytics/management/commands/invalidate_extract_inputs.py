from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.changes import COLLECTION, DATASET, mark
from analytics.models import ExtractInvalidItem
from features.models import FeatMap


class Command(BaseCommand):
    help = (
        "Record that a dataset's or collection's inputs changed out of band, so "
        "its results and coverage are reset and recomputed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dataset", type=int, action="append", dest="datasets", default=[])
        parser.add_argument("--collection", type=int, action="append", dest="collections", default=[])

    def handle(self, *args, **options):
        """The same durable reset the triggers record for an edit.

        For repair and import workflows that changed what an extraction reads
        without going through the tables the triggers watch -- most often a
        replaced raster. It cannot make a concurrent in-place file rewrite safe,
        or detect one: publish replacement files at a new path and update the
        resource's path instead, and the trigger does this for you.
        """
        if not options["datasets"] and not options["collections"]:
            raise CommandError("Name at least one --dataset or --collection")
        with transaction.atomic():
            mark(DATASET, options["datasets"], rewind_from=0, sync_pairs=True,
                 reset_tasks=True, reset_coverage=True)
            # A collection's results reset as a targeted reset of every one of
            # its features; its coverage resets as a whole.
            for fc_id in options["collections"]:
                fm_ids = FeatMap.objects.filter(fc_id=fc_id).values_list("id", flat=True)
                mark(COLLECTION, [fc_id], rewind_from=0, reset_coverage=True,
                     items=(ExtractInvalidItem.FEATURE, fm_ids))
        self.stdout.write(self.style.SUCCESS(
            f"Recorded resets for datasets {options['datasets']} and collections "
            f"{options['collections']}. Sync applies them on its next runs."
        ))
