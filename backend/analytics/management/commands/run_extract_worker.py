from django.conf import settings
from django.core.management.base import BaseCommand

from analytics import metrics
from analytics.extract_worker import ExtractWorker


class Command(BaseCommand):
    help = "Claim and run extract tasks until stopped (SIGTERM or SIGINT)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--concurrency",
            type=int,
            default=1,
            help="Worker processes, each running one chunk of tasks at a time",
        )
        parser.add_argument(
            "--max-chunks-per-child",
            type=int,
            default=100,
            help="Chunks a worker process runs before it is replaced, reclaiming leaked memory",
        )
        parser.add_argument(
            "--idle-seconds",
            type=float,
            default=None,
            help="Wait after an empty claim (default: EXTRACT_WORKER_IDLE_SECONDS)",
        )

    def handle(self, *args, **options):
        idle_seconds = options["idle_seconds"]
        if idle_seconds is None:
            idle_seconds = settings.EXTRACT_WORKER_IDLE_SECONDS

        metrics.start_worker_exporter(settings.WORKER_METRICS_PORT)
        self.stdout.write(
            f"Extract worker: {options['concurrency']} processes, "
            f"{options['max_chunks_per_child']} chunks per process, "
            f"{idle_seconds}s idle wait"
        )
        ExtractWorker(
            concurrency=options["concurrency"],
            max_chunks_per_child=options["max_chunks_per_child"],
            idle_seconds=idle_seconds,
        ).run()
