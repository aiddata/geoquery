from django.core.management.base import BaseCommand


class BaseIngestCommand(BaseCommand):
    """Base class for ingest management commands.

    After a successful run of handle(), dispatches trigger_coverage_and_extract
    so coverage records are created/checked and extract tasks are built without
    manual intervention.

    A subclass's handle() may set ``skip_post_ingest_hooks = True`` to suppress
    that dispatch, for runs that change nothing coverage or extraction depends
    on. handle() runs before the dispatch, so a flag set there is honoured.
    """

    #: Set by handle() to suppress the post-ingest dispatch for this run.
    skip_post_ingest_hooks = False

    def execute(self, *args, **options):
        result = super().execute(*args, **options)

        if self.skip_post_ingest_hooks:
            self.stdout.write(
                "Skipped coverage and extract tasks (nothing they depend on changed)."
            )
            return result

        from analytics.tasks.maintenance import trigger_coverage_and_extract

        trigger_coverage_and_extract.delay()
        self.stdout.write("Triggered coverage and extract tasks.")
        return result
