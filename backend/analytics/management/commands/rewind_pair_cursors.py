from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from analytics.changes import DATASET, mark


class Command(BaseCommand):
    help = (
        "Rewind pair cursors and coverage watermarks so features are scanned "
        "again. Recorded as a durable dataset rewind that sync applies."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dataset", type=int, action="append", dest="datasets", default=[])
        parser.add_argument("--all", action="store_true", help="Every dataset")
        parser.add_argument(
            "--to", type=int, default=0,
            help="Rewind to this feat_map id: everything above it is scanned again (default 0)",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        """Never edits a cursor directly.

        A cursor promises that every eligible feature below it is accounted
        for, and only sync may move one backwards while holding the dataset's
        state, re-tokening the leases it affects. This records the request
        the same way a trigger would, so it survives a crash and waits for any
        reconciliation already in progress. Rewinding re-scans; it does not
        recompute: features with tasks are skipped again. To recompute, use
        invalidate_extract_inputs.
        """
        if options["all"] == bool(options["datasets"]):
            raise CommandError("Name --dataset ids or --all (not both)")
        with connection.cursor() as cursor:
            if options["all"]:
                cursor.execute("SELECT id FROM datasets ORDER BY id")
                datasets = [r[0] for r in cursor.fetchall()]
            else:
                datasets = sorted(set(options["datasets"]))
            cursor.execute(
                """
                SELECT dataset_id, count(*) FILTER (WHERE cursor_fm_id > %s)
                FROM extract_task_build_progress
                WHERE current AND dataset_id = ANY(%s::int[])
                GROUP BY dataset_id ORDER BY dataset_id
                """,
                [options["to"], datasets],
            )
            pairs = dict(cursor.fetchall())
            cursor.execute(
                """
                SELECT dataset_id, covered_up_to_fm_id FROM extract_coverage_progress
                WHERE dataset_id = ANY(%s::int[]) AND covered_up_to_fm_id > %s
                """,
                [datasets, options["to"]],
            )
            coverage = dict(cursor.fetchall())

        for dataset_id in datasets:
            line = f"dataset {dataset_id}: {pairs.get(dataset_id, 0)} pair cursor(s)"
            if dataset_id in coverage:
                line += f", coverage watermark {coverage[dataset_id]}"
            self.stdout.write(f"{line} -> {options['to']}")
        if options["dry_run"]:
            self.stdout.write("Dry run: nothing recorded.")
            return
        mark(DATASET, datasets, rewind_from=options["to"])
        self.stdout.write(self.style.SUCCESS(
            f"Recorded rewinds for {len(datasets)} dataset(s). Sync applies them on its next runs."
        ))
