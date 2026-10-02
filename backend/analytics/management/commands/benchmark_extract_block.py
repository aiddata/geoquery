import math
import time
import uuid
from warnings import catch_warnings

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from analytics import blocks
from analytics.models import ExtractTaskBuildProgress, ProcessingOption
from analytics.tasks.processing import get_func
from datasets.models import DatasetResource


class _Rollback(Exception):
    pass


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b and type(a) is type(b)


class Command(BaseCommand):
    help = (
        "Compare block extraction with the per-task path on real data: check that "
        "both produce identical values, and time each. Reads only, unless --write "
        "is given, which also times the block's write transaction and then rolls "
        "it back."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--resource", type=int, required=True,
            help="DatasetResource id. A grouped dataset uses the whole bucket containing it.",
        )
        parser.add_argument("--features", type=int, default=500, help="Feature count (default 500).")
        parser.add_argument(
            "--after-fm-id", type=int, default=0,
            help="Start the range after this feat_map id (default 0).",
        )
        parser.add_argument(
            "--write", action="store_true",
            help="Also time the write transaction, then roll it back. Holds row locks "
            "on any existing tasks in the range while it runs.",
        )

    def handle(self, *args, resource, features, after_fm_id, write, **options):
        try:
            res = DatasetResource.objects.select_related("dataset").get(id=resource)
        except DatasetResource.DoesNotExist:
            raise CommandError(f"No DatasetResource {resource}")
        dataset = res.dataset

        pair = (
            ExtractTaskBuildProgress.objects.filter(resource_ids__contains=[resource])
            .order_by("id").first()
        )
        resource_ids = list(pair.resource_ids) if pair else [resource]
        pos = ProcessingOption.objects.filter(dataset=dataset, active=True).order_by("id")
        if not pos:
            raise CommandError(f"Dataset {dataset.id} has no active processing options")

        with connection.cursor() as cursor:
            cursor.execute(blocks._MAX_FEAT_MAP_ID_SQL)
            max_fm_id = cursor.fetchone()[0]
            cursor.execute(blocks._RANGE_SQL, [after_fm_id, max_fm_id, features])
            feature_rows = cursor.fetchall()
        if not feature_rows:
            raise CommandError("No features in that range")

        block = blocks.Block(
            token=uuid.uuid4(),
            pair_ids=[],
            dataset_id=dataset.id,
            resource_ids=resource_ids,
            task_group_period=dataset.task_group_period,
            options=[(po.id, po.function, po.short_name, po.kwargs) for po in pos],
            lo=after_fm_id,
            hi=feature_rows[-1][0],
            features=feature_rows,
        )
        geometries, resources, opts = blocks.load_inputs(
            block, {geom_id for _, geom_id in feature_rows}
        )
        n_tasks = len(geometries) * len(opts)
        self.stdout.write(
            f"dataset {dataset.id} ({dataset.name}), resources {resource_ids}, "
            f"{len(geometries)} distinct geometries x {len(opts)} options "
            f"[{', '.join(o.function for o in opts)}]"
        )

        # Today's path: one processor call per geometry, option and resource.
        expected = {}
        wall, cpu = time.perf_counter(), time.process_time()
        for geom_id, geom in geometries.items():
            for option in opts:
                func = get_func(option.function)
                for position, (_rid, path) in enumerate(resources):
                    try:
                        with catch_warnings(record=True):
                            results = func(geom, path, **option.op_kwargs)
                    except Exception:
                        continue
                    target = expected.setdefault((geom_id, option.po_id), {})
                    for name, value in results:
                        target.setdefault(name, {})[position] = value
        task_wall, task_cpu = time.perf_counter() - wall, time.process_time() - cpu

        wall, cpu = time.perf_counter(), time.process_time()
        produced, failures = blocks.compute(geometries, resources, opts)
        block_wall, block_cpu = time.perf_counter() - wall, time.process_time() - cpu

        mismatches = []
        for key in set(expected) | set(produced):
            want, got = expected.get(key, {}), produced.get(key, {})
            if set(want) != set(got):
                mismatches.append((key, "names", sorted(want), sorted(got)))
                continue
            for name in want:
                for position in set(want[name]) | set(got[name]):
                    a, b = want[name].get(position), got[name].get(position)
                    if not _same(a, b):
                        mismatches.append((key, name, position, a, b))

        def rate(count, seconds):
            return f"{count / seconds:,.0f}/s" if seconds else "n/a"

        self.stdout.write(
            f"per-task: {task_wall:.2f}s wall, {task_cpu:.2f}s cpu -> "
            f"{rate(n_tasks, task_cpu)} tasks per core"
        )
        self.stdout.write(
            f"block:    {block_wall:.2f}s wall, {block_cpu:.2f}s cpu -> "
            f"{rate(n_tasks, block_cpu)} tasks per core"
        )
        if block_wall:
            self.stdout.write(f"speedup (wall): {task_wall / block_wall:.1f}x")
        self.stdout.write(f"failures in block path: {sum(len(v) for v in failures.values())}")
        if mismatches:
            self.stdout.write(self.style.ERROR(f"{len(mismatches)} mismatches; first 10:"))
            for m in mismatches[:10]:
                self.stdout.write(f"  {m}")
        else:
            self.stdout.write(self.style.SUCCESS("values identical"))

        if write:
            self._time_write(block, pair, produced, failures)

    def _time_write(self, block, pair, produced, failures):
        if pair is None:
            raise CommandError("--write needs a progress pair for this resource; none exists")
        block.pair_ids = list(
            ExtractTaskBuildProgress.objects.filter(
                resource_ids=block.resource_ids, po_id__in=[o[0] for o in block.options]
            ).values_list("id", flat=True)
        )
        try:
            with transaction.atomic():
                # Lease the pairs inside the rolled-back transaction, so the
                # write's fence passes without touching real lease state.
                ExtractTaskBuildProgress.objects.filter(id__in=block.pair_ids).update(
                    block_claim_token=block.token
                )
                needed = blocks.scan_block(block)
                tasks, data = blocks.task_rows(block, needed, produced, failures)
                started = time.perf_counter()
                counts = blocks.write_block(block, tasks, data)
                elapsed = time.perf_counter() - started
                raise _Rollback
        except _Rollback:
            pass
        if not tasks:
            self.stdout.write(
                "write: nothing to time -- every task in this range is already done "
                "or in flight; choose another range with --after-fm-id"
            )
            return
        self.stdout.write(
            f"write: {len(tasks)} tasks, {len(data)} data rows in {elapsed:.2f}s "
            f"({len(tasks) / elapsed:,.0f} tasks/s; rolled back); by status {counts}"
        )
