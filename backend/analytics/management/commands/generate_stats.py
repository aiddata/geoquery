import time

from django.core.management.base import BaseCommand

from stats.builder import StatsBuilder


class Command(BaseCommand):
    help = "Generate an HTML statistics report for GeoQuery request history."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="../results/geoquery_stats.html",
            help="Path to write the output HTML file (default: ../results/geoquery_stats.html)",
        )

    def handle(self, *args, **options):
        output = options["output"]
        self.stdout.write(f"Generating stats report → {output}")
        t0 = time.time()

        builder = StatsBuilder(output)
        status = builder.build()

        if status == "Success":
            self.stdout.write(
                self.style.SUCCESS(f"Stats report generated in {time.time() - t0:.1f}s: {output}")
            )
        else:
            self.stdout.write(self.style.ERROR(f"Failed: {status}"))
