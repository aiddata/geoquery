import json

from django.core.management.base import BaseCommand
from django.db import connection

from analytics.changes import jsonb
from analytics.sync import health
from analytics.tasks.leases import lease_health


class Command(BaseCommand):
    help = "Report extraction health: dirty input scopes, leases, pair errors and demand."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine-readable output")
        parser.add_argument("--limit", type=int, default=20, help="Rows per list")

    def handle(self, *args, **options):
        report = {"scopes": health(), "leases": lease_health()}
        with connection.cursor() as cursor:
            cursor.execute("SELECT extract_work_demand()")
            report["demand"] = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT kind, object_id, generation, applied_generation, bootstrap_pending,
                       sync_pairs, reset_tasks, reset_coverage, rewind_from,
                       checkpoint, retry_after, last_error
                FROM extract_input_state
                WHERE generation <> applied_generation OR bootstrap_pending
                ORDER BY last_error IS NULL, updated_at
                LIMIT %s
                """,
                [options["limit"]],
            )
            columns = [c[0] for c in cursor.description]
            report["dirty"] = [dict(zip(columns, row)) for row in cursor.fetchall()]
            for row in report["dirty"]:
                row["checkpoint"] = jsonb(row["checkpoint"])
            cursor.execute(
                """
                SELECT id, dataset_id, po_id, resource_ids, cursor_fm_id, retry_after, last_error
                FROM extract_task_build_progress
                WHERE current AND last_error IS NOT NULL
                ORDER BY retry_after LIMIT %s
                """,
                [options["limit"]],
            )
            columns = [c[0] for c in cursor.description]
            report["pair_errors"] = [dict(zip(columns, row)) for row in cursor.fetchall()]

        if options["json"]:
            self.stdout.write(json.dumps(report, default=str, indent=2))
            return
        self.stdout.write(f"demand: {report['demand']}")
        for kind, values in sorted(report["scopes"].items()):
            self.stdout.write(f"{kind} scopes: {values}")
        self.stdout.write(f"leases: {report['leases']}")
        for row in report["dirty"]:
            self.stdout.write(f"  dirty {row['kind']} {row['object_id']}: {row}")
        for row in report["pair_errors"]:
            self.stdout.write(f"  pair {row['id']} error: {row['last_error']}")
