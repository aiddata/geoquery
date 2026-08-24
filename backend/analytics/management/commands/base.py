from django.core.management.base import BaseCommand


class BaseIngestCommand(BaseCommand):
    """Base class for ingest management commands.

    After a successful run of handle(), dispatches trigger_coverage_and_extract
    so coverage records are created/checked and extract tasks are built without
    manual intervention.
    """

    def execute(self, *args, **options):
        result = super().execute(*args, **options)
        from analytics.tasks.maintenance import trigger_coverage_and_extract

        trigger_coverage_and_extract.delay()
        self.stdout.write("Triggered coverage and extract tasks.")
        return result
