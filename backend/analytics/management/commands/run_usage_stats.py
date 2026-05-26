"""
TODO: this will replace the code that ran on the MongoDB side of the old GeoQuery.
"""
import time

from django.core.management.base import BaseCommand
from django.db import connection

from analytics.tasks.stats import xxxx


class Command(BaseCommand):
    help = "Run usage stats calculations for datasets and features. This is the replacement for the old MongoDB-based stats calculation code."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Do not write any outputs to file, just print to stdout/log",
        )


    def handle(self, *args, **options):
        """
        TODO: call various usage stat funcs based on the command args provided
        """
        return
