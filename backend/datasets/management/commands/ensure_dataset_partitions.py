import logging

from django.core.management.base import BaseCommand

from datasets.partitions import (
    DEFAULT_LOCK_TIMEOUT,
    PARTITIONED_PARENTS,
    ensure_all_dataset_partitions,
    ensure_dataset_partitions,
    missing_partitions,
    rows_parked_in_default,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Create the per-dataset extract_tasks/extract_data partitions for any "
        "Dataset missing them. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset-id",
            type=int,
            default=None,
            help="Only this dataset, instead of every dataset missing partitions",
        )
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Report what is missing without creating anything",
        )
        parser.add_argument(
            "--lock-timeout",
            default=DEFAULT_LOCK_TIMEOUT,
            help=(
                "How long to wait for ACCESS EXCLUSIVE on the partitioned parent "
                f"before giving up and leaving it for a retry (default {DEFAULT_LOCK_TIMEOUT}). "
                "Raise it only in a quiet window: the DDL queues ahead of "
                "statements arriving behind it, so a long wait stalls the fleet, "
                "not just this command."
            ),
        )

    def handle(self, *args, **options):
        dataset_id = options["dataset_id"]
        dry_run = options["dry_run"]
        lock_timeout = options["lock_timeout"]

        if dry_run:
            self._report(dataset_id)
            return

        if dataset_id is not None:
            parked = rows_parked_in_default(dataset_id)
            if any(parked.values()):
                self.stderr.write(
                    self.style.ERROR(
                        f"dataset {dataset_id} has rows in DEFAULT "
                        f"({', '.join(f'{p}={n}' for p, n in parked.items() if n)}). "
                        "Postgres will refuse to create the partition until they "
                        "are relocated out of the DEFAULT partition."
                    )
                )
                return
            created = ensure_dataset_partitions(dataset_id, lock_timeout=lock_timeout)
            blocked = []
        else:
            created, blocked = ensure_all_dataset_partitions(lock_timeout=lock_timeout)

        for name in created:
            self.stdout.write(self.style.SUCCESS(f"created {name}"))
        for ds in blocked:
            self.stderr.write(
                self.style.ERROR(f"dataset {ds} blocked: rows already in DEFAULT")
            )
        if not created and not blocked:
            self.stdout.write("nothing to do; every dataset already has its partitions")
        elif created:
            self.stdout.write(f"created {len(created)} partition(s)")

    def _report(self, dataset_id):
        from datasets.models import Dataset

        ids = (
            [dataset_id]
            if dataset_id is not None
            else list(Dataset.objects.values_list("id", flat=True).order_by("id"))
        )
        total = 0
        for ds in ids:
            outstanding = missing_partitions(ds)
            if not outstanding:
                continue
            total += len(outstanding)
            parked = rows_parked_in_default(ds)
            note = ""
            if any(parked.values()):
                note = (
                    "  [BLOCKED: rows in DEFAULT -- "
                    + ", ".join(f"{p}={n}" for p, n in parked.items() if n)
                    + "]"
                )
            self.stdout.write(
                f"dataset {ds}: missing {', '.join(c for _, c in outstanding)}{note}"
            )
        if total == 0:
            self.stdout.write(
                "nothing missing; every dataset has partitions on "
                + " and ".join(PARTITIONED_PARENTS)
            )
        else:
            self.stdout.write(f"{total} partition(s) would be created")
