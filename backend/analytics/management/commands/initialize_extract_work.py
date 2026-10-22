"""Bring a database created before pair cursor leases under the new system.

Migration 0031 retires every pair, resets every cursor to 0 and marks every
existing dataset's input state bootstrap_pending. Sync leaves those datasets
alone, and no worker touches them, until this command has, for each one:

1. reconciled its pairs (the same reconciliation sync uses), so the current
   sets exist with ids;
2. backfilled pair_id on its legacy tasks, in bounded chunks: a task whose
   (resource_ids, po) has a pair row gets that pair's id, current or
   retired; a grouped set nothing names any more gets a new retired pair, so
   readers never mistake it for current; an unmatched single-resource task
   (a request's) stays NULL;
3. deleted its legacy coverage, status -1 placeholders included, in bounded
   chunks, so the coverage watermark sync creates rebuilds it from 0;
4. cleared bootstrap_pending. The scope is still dirty, so ordinary sync then
   publishes it: coverage progress created at 0, cursors rewound to 0.

Each chunk is its own transaction, and progress is checkpointed in the
dataset's input state, so the command can be interrupted and run again. A
dataset already initialized is skipped: running it twice never resets
anything. A change to a dataset's inputs while it is being initialized
clears the checkpoint and that dataset simply starts over.

Run it with the old builder, coverage and processing workers stopped, after
migrating and before enabling the new workers. Datasets created after the
migration never need it.
"""

import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from analytics.changes import jsonb
from analytics.sync import SyncConfigError, reconcile_pairs

_PHASES = ("pairs", "provenance", "coverage", "done")


class Command(BaseCommand):
    help = "Initialize bootstrap-pending datasets for pair cursor leases (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset", type=int, action="append", dest="datasets",
            help="Only this dataset id (repeatable). Default: every bootstrap-pending dataset.",
        )
        parser.add_argument(
            "--chunk-size", type=int, default=None,
            help="Tasks or coverage rows per transaction (default EXTRACT_RESET_CHUNK_SIZE).",
        )
        parser.add_argument(
            "--max-chunks", type=int, default=0,
            help="Stop after this many chunk transactions (0 = no limit).",
        )
        parser.add_argument(
            "--status", action="store_true",
            help="List bootstrap-pending datasets and their checkpoints, and change nothing.",
        )

    def handle(self, *args, **options):
        pending = _pending_datasets(options["datasets"])
        if options["status"]:
            for dataset_id, checkpoint in pending:
                self.stdout.write(f"dataset {dataset_id}: {checkpoint.get('bootstrap') or 'not started'}")
            self.stdout.write(f"{len(pending)} dataset(s) pending")
            return

        chunk_size = options["chunk_size"] or settings.EXTRACT_RESET_CHUNK_SIZE
        budget = options["max_chunks"] or None
        chunks = 0
        unfinished = []
        for dataset_id, _ in pending:
            started = time.monotonic()
            while True:
                if budget is not None and chunks >= budget:
                    self.stdout.write(self.style.WARNING(f"Stopped after {chunks} chunks; run again to continue"))
                    return
                try:
                    result = initialize_chunk(dataset_id, chunk_size)
                except SyncConfigError as exc:
                    self.stdout.write(self.style.ERROR(f"dataset {dataset_id}: {exc}; fix it and run again"))
                    result = "error"
                    break
                chunks += 1
                if result in ("done", "busy", "gone"):
                    break
            elapsed = time.monotonic() - started
            if result == "done":
                self.stdout.write(self.style.SUCCESS(f"dataset {dataset_id}: initialized in {elapsed:.1f}s"))
            elif result == "busy":
                self.stdout.write(self.style.WARNING(
                    f"dataset {dataset_id}: its input state is locked by another transaction; run again"
                ))
            if result in ("error", "busy"):
                unfinished.append(dataset_id)
        # A release step must not report success while a dataset stays
        # bootstrap_pending: its work and results stay hidden until it is done.
        if unfinished:
            raise CommandError(
                f"{len(unfinished)} of {len(pending)} dataset(s) not initialized "
                f"({', '.join(map(str, unfinished))}); fix the errors above and run again"
            )
        self.stdout.write(self.style.SUCCESS(
            f"{len(pending)} dataset(s) processed. Sync publishes them on its next runs."
        ))


def _pending_datasets(only=None):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT object_id, checkpoint FROM extract_input_state
            WHERE kind = 'dataset' AND bootstrap_pending
              AND (%s::int[] IS NULL OR object_id = ANY(%s::int[]))
            ORDER BY object_id
            """,
            [only, only],
        )
        return [(object_id, jsonb(checkpoint) or {}) for object_id, checkpoint in cursor.fetchall()]


def initialize_chunk(dataset_id, chunk_size):
    """One transaction of one dataset's initialization.

    Returns "progress", "done", "busy" (state locked elsewhere) or "gone"
    (not pending any more).
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT checkpoint FROM extract_input_state
                WHERE kind = 'dataset' AND object_id = %s AND bootstrap_pending
                FOR UPDATE SKIP LOCKED
                """,
                [dataset_id],
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT bootstrap_pending FROM extract_input_state WHERE kind = 'dataset' AND object_id = %s",
                    [dataset_id],
                )
                state = cursor.fetchone()
                return "busy" if state and state[0] else "gone"
            checkpoint = dict(jsonb(row[0]) or {})
            progress = dict(checkpoint.get("bootstrap") or {"phase": "pairs"})
            phase = progress["phase"]

            if phase == "pairs":
                reconcile_pairs(cursor, dataset_id)
                progress = {"phase": "provenance", "fm_id": 0, "task_id": 0}
            elif phase == "provenance":
                if _backfill_provenance(cursor, dataset_id, progress, chunk_size):
                    progress = {"phase": "coverage", "geom_id": 0}
            elif phase == "coverage":
                if _delete_legacy_coverage(cursor, dataset_id, progress, chunk_size):
                    progress = {"phase": "done"}
            if progress["phase"] == "done":
                cursor.execute(
                    """
                    UPDATE extract_input_state
                    SET bootstrap_pending = false, checkpoint = '{}'::jsonb,
                        updated_at = clock_timestamp(), retry_after = now()
                    WHERE kind = 'dataset' AND object_id = %s
                    """,
                    [dataset_id],
                )
                return "done"
            checkpoint["bootstrap"] = progress
            cursor.execute(
                "UPDATE extract_input_state SET checkpoint = %s::jsonb WHERE kind = 'dataset' AND object_id = %s",
                [json.dumps(checkpoint), dataset_id],
            )
            return "progress"


def _backfill_provenance(cursor, dataset_id, progress, chunk_size):
    """Name the pair of the next chunk of legacy tasks. True when finished."""
    cursor.execute(
        """
        SELECT fm_id, id, resource_ids, po_id, task_group_period FROM extract_tasks
        WHERE dataset_id = %s AND (fm_id, id) > (%s, %s)
        ORDER BY fm_id, id LIMIT %s
        """,
        [dataset_id, progress["fm_id"], progress["task_id"], chunk_size],
    )
    rows = cursor.fetchall()
    if rows:
        # Grouped sets no pair names any more: retired provenance, never
        # current, so readers cannot mistake an obsolete bucket for the
        # present one.
        grouped = sorted({(tuple(ids), po_id, period) for _, _, ids, po_id, period in rows if len(ids) > 1})
        for ids, po_id, period in grouped:
            cursor.execute(
                """
                INSERT INTO extract_task_build_progress
                    (resource_ids, po_id, dataset_id, task_group_period, current, cursor_fm_id)
                VALUES (%s::int[], %s, %s, %s, false, 0)
                ON CONFLICT (resource_ids, po_id) DO NOTHING
                """,
                [list(ids), po_id, dataset_id, period],
            )
        cursor.execute(
            """
            UPDATE extract_tasks AS t SET pair_id = p.id
            FROM extract_task_build_progress p
            WHERE t.dataset_id = %s AND t.id = ANY(%s::bigint[])
              AND t.dataset_id = ANY(%s::int[])
              AND t.pair_id IS NULL AND t.kwargs IS NULL
              AND p.resource_ids = t.resource_ids AND p.po_id = t.po_id
            """,
            [dataset_id, [task_id for _, task_id, *_ in rows], [dataset_id]],
        )
    if len(rows) < chunk_size:
        return True
    progress["fm_id"], progress["task_id"] = rows[-1][0], rows[-1][1]
    return False


def _delete_legacy_coverage(cursor, dataset_id, progress, chunk_size):
    """Delete the next chunk of the dataset's coverage rows. True when finished."""
    cursor.execute(
        """
        WITH doomed AS (
            SELECT geom_id FROM coverage
            WHERE dataset_id = %s AND geom_id > %s
            ORDER BY geom_id LIMIT %s
        )
        DELETE FROM coverage c USING doomed
        WHERE c.dataset_id = %s AND c.geom_id = doomed.geom_id
        RETURNING c.geom_id
        """,
        [dataset_id, progress["geom_id"], chunk_size, dataset_id],
    )
    geoms = [r[0] for r in cursor.fetchall()]
    if len(geoms) < chunk_size:
        return True
    progress["geom_id"] = max(geoms)
    return False
