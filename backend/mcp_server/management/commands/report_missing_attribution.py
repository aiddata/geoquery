"""List active datasets and boundaries missing a license or a citation.

Attribution is only as good as the metadata behind it: every surface that
cites a dataset -- the API, the docs site, the results zip, the MCP server --
degrades to "not recorded, check the source" when the fields are empty. This
command is the curation worklist that closes that gap.
"""

from django.core.management.base import BaseCommand

from datasets.models import Dataset
from features.models import FeatureCollection


class Command(BaseCommand):
    help = "Report active datasets / boundaries with no license or citation recorded."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Include inactive records (default: active only).",
        )
        parser.add_argument(
            "--public-only",
            action="store_true",
            help="Only report records that are public, i.e. visible to anyone.",
        )

    def handle(self, *args, **options):
        total_missing = 0
        for label, qs, order in (
            ("Datasets", Dataset.objects.all(), ["name"]),
            ("Boundaries", FeatureCollection.objects.all(), ["group_level", "name"]),
        ):
            if not options["all"]:
                qs = qs.filter(active=True)
            if options["public_only"]:
                qs = qs.filter(public=True)

            rows = [
                obj
                for obj in qs.order_by(*order)
                if not obj.license or not obj.citation
            ]
            total_missing += len(rows)

            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{label} ({len(rows)})"))
            if not rows:
                self.stdout.write("  nothing missing")
                continue
            for obj in rows:
                missing = ", ".join(
                    m
                    for m in (
                        "license" if not obj.license else None,
                        "citation" if not obj.citation else None,
                    )
                    if m
                )
                source = obj.source_name or obj.source_url or "no source recorded"
                self.stdout.write(f"  {obj.name}: missing {missing} ({source})")

        style = self.style.WARNING if total_missing else self.style.SUCCESS
        self.stdout.write(
            style(f"\n{total_missing} record(s) missing license or citation.")
        )
