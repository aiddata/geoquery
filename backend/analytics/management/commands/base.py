from django.core.management.base import BaseCommand


class BaseIngestCommand(BaseCommand):
    """Base class for ingest management commands.

    After a successful run of handle(), wakes the extract sync
    (analytics.tasks.maintenance.sync_extract_work) once, after the ingest's
    transaction has committed. The ingest itself needs nothing from here: the
    database triggers on datasets, resources, options, collections and
    features already recorded every change it made, durably and in the same
    transaction. The wake only means sync starts on them now rather than at
    its next beat tick, and a lost wake costs nothing but that wait.

    A subclass's handle() may set ``skip_post_ingest_hooks = True`` to suppress
    the wake, for runs that change nothing extraction depends on. handle()
    runs before the wake, so a flag set there is honoured.
    """

    #: Set by handle() to suppress the post-ingest wake for this run.
    skip_post_ingest_hooks = False

    def execute(self, *args, **options):
        result = super().execute(*args, **options)

        if self.skip_post_ingest_hooks:
            self.stdout.write(
                "Skipped waking extract sync (nothing it depends on changed)."
            )
            return result

        from analytics.changes import wake_sync

        wake_sync()
        self.stdout.write("Woke extract sync.")
        return result
