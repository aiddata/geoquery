import threading
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from analytics.models import ExtractData, ExtractTask, ProcessingOption
from datasets.models import Dataset, DatasetResource
from datasets.partitions import (
    PARTITIONED_PARENTS,
    ensure_all_dataset_partitions,
    ensure_dataset_partitions,
    missing_partitions,
    partition_name,
    rows_parked_in_default,
)
from features.models import Feature, FeatMap, FeatureCollection


def _exists(name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_class WHERE relname = %s", [name])
        return cursor.fetchone() is not None


def _make_extract_task(dataset):
    """Build the minimal real object graph an ExtractTask needs.

    Real rows, not a synthetic id: extract_data has an FK to extract_tasks
    and Django's TestCase defers FK validation to teardown, so a made-up
    extract_task_id fails the whole test case during cleanup instead of at
    the line that wrote it.
    """
    resource = DatasetResource.objects.create(
        dataset=dataset, name=f"{dataset.name}-2020", path="2020.tif"
    )
    po = ProcessingOption.objects.create(
        dataset=dataset,
        short_name="mean",
        function="rasterstats_default_mean",
        active=True,
    )
    fc = FeatureCollection.objects.create(
        name=f"fc-{dataset.id}", path=f"/data/fc-{dataset.id}", active=True
    )
    fm = FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))
    return ExtractTask.objects.create(
        resource_ids=[resource.id],
        dataset_id=dataset.id,
        fm=fm,
        po=po,
        kwargs={},
    )


class PartitionNamingTests(TestCase):
    def test_names_match_migration_0021_convention(self):
        self.assertEqual(partition_name("extract_tasks", 42), "extract_tasks_ds_42")
        self.assertEqual(partition_name("extract_data", 42), "extract_data_ds_42")

    def test_rejects_ids_that_are_unsafe_to_interpolate(self):
        # The id lands in an identifier and a partition bound, neither of
        # which can be a bind parameter, so anything but a positive int has
        # to be refused rather than formatted into DDL.
        for bad in ["1; DROP TABLE extract_tasks", "1", 1.0, None]:
            with self.assertRaises(TypeError):
                missing_partitions(bad)
        # bool is an int subclass; it would name a partition ..._ds_True
        with self.assertRaises(TypeError):
            missing_partitions(True)
        for bad in [0, -1]:
            with self.assertRaises(ValueError):
                missing_partitions(bad)


class EnsureDatasetPartitionsTests(TestCase):
    """DDL here rolls back with the TestCase, leaving the test schema clean.

    A freshly migrated test database has only the DEFAULT partitions:
    migration 0021 creates per-dataset partitions by iterating over the
    Dataset rows that exist when it runs, and there are none at that point.
    So a Dataset created in a test starts with no partitions of its own,
    which is exactly the case this module exists to handle.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(name="ds", path="/data/ds", type="raster")

    def test_both_partitions_are_missing_to_begin_with(self):
        self.assertEqual(
            sorted(c for _, c in missing_partitions(self.dataset.id)),
            sorted(partition_name(p, self.dataset.id) for p in PARTITIONED_PARENTS),
        )

    def test_creates_a_partition_on_every_partitioned_parent(self):
        created = ensure_dataset_partitions(self.dataset.id)
        self.assertEqual(
            sorted(created),
            sorted(partition_name(p, self.dataset.id) for p in PARTITIONED_PARENTS),
        )
        for parent in PARTITIONED_PARENTS:
            self.assertTrue(_exists(partition_name(parent, self.dataset.id)))
        self.assertEqual(missing_partitions(self.dataset.id), [])

    def test_is_idempotent(self):
        ensure_dataset_partitions(self.dataset.id)
        self.assertEqual(ensure_dataset_partitions(self.dataset.id), [])

    def test_rows_route_to_the_new_partition_not_default(self):
        # The point of the whole module: with the partition in place, this
        # dataset's rows stop landing in DEFAULT.
        ensure_dataset_partitions(self.dataset.id)
        task = _make_extract_task(self.dataset)
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id, name="mean"
        )
        with connection.cursor() as cursor:
            for parent in PARTITIONED_PARENTS:
                child = partition_name(parent, self.dataset.id)
                cursor.execute(f'SELECT count(*) FROM "{child}"')
                self.assertEqual(cursor.fetchone()[0], 1, f"{child} should hold the row")
                cursor.execute(f'SELECT count(*) FROM "{parent}_default"')
                self.assertEqual(cursor.fetchone()[0], 0, f"{parent}_default should be empty")

    def test_missing_partitions_takes_no_lock_on_the_parents(self):
        # The whole reason this is a catalog lookup instead of
        # CREATE TABLE IF NOT EXISTS: in steady state it runs for every
        # dataset on every sweep, and must not reach for ACCESS EXCLUSIVE on
        # extract_tasks to be told the partition is already there.
        missing_partitions(self.dataset.id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FROM pg_locks l
                JOIN pg_class c ON c.oid = l.relation
                WHERE l.pid = pg_backend_pid()
                  AND c.relname = ANY(%s)
                  AND l.mode = 'AccessExclusiveLock'
                """,
                [list(PARTITIONED_PARENTS)],
            )
            self.assertEqual(cursor.fetchone()[0], 0)


class RowsParkedInDefaultTests(TestCase):
    def setUp(self):
        self.dataset = Dataset.objects.create(name="ds", path="/data/ds", type="raster")

    def test_reports_zero_when_default_is_empty(self):
        self.assertEqual(
            rows_parked_in_default(self.dataset.id),
            {p: 0 for p in PARTITIONED_PARENTS},
        )

    def test_detects_rows_that_landed_in_default(self):
        # No partition for this dataset yet, so the task goes to DEFAULT --
        # the state that makes creating the partition impossible later.
        _make_extract_task(self.dataset)
        self.assertEqual(rows_parked_in_default(self.dataset.id)["extract_tasks"], 1)

    def test_postgres_refuses_the_partition_once_rows_are_in_default(self):
        """Documents the ratchet this module exists to stay ahead of."""
        _make_extract_task(self.dataset)
        with self.assertRaises(Exception) as ctx:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f'CREATE TABLE "{partition_name("extract_tasks", self.dataset.id)}" '
                        f"PARTITION OF extract_tasks FOR VALUES IN ({self.dataset.id})"
                    )
        self.assertIn("default partition", str(ctx.exception).lower())


class EnsureAllDatasetPartitionsTests(TestCase):
    def test_partitions_every_dataset_missing_them(self):
        a = Dataset.objects.create(name="a", path="/data/a", type="raster")
        b = Dataset.objects.create(name="b", path="/data/b", type="raster")
        created, blocked = ensure_all_dataset_partitions()
        self.assertEqual(blocked, [])
        for ds in (a, b):
            for parent in PARTITIONED_PARENTS:
                self.assertIn(partition_name(parent, ds.id), created)

    def test_reports_blocked_datasets_instead_of_failing_the_whole_sweep(self):
        blocked_ds = Dataset.objects.create(name="a", path="/data/a", type="raster")
        ok_ds = Dataset.objects.create(name="b", path="/data/b", type="raster")
        _make_extract_task(blocked_ds)

        created, blocked = ensure_all_dataset_partitions()

        self.assertEqual(blocked, [blocked_ds.id])
        # The healthy dataset is still partitioned -- one blocked dataset must
        # not strand every dataset after it.
        self.assertIn(partition_name("extract_tasks", ok_ds.id), created)
        self.assertNotIn(partition_name("extract_tasks", blocked_ds.id), created)


class DatasetCreatedSignalTests(TestCase):
    def test_enqueues_the_task_once_on_creation(self):
        with patch("datasets.tasks.ensure_dataset_partitions_task.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                dataset = Dataset.objects.create(
                    name="ds", path="/data/ds", type="raster"
                )
        delay.assert_called_once_with(dataset.id)

    def test_does_not_enqueue_on_later_saves(self):
        with self.captureOnCommitCallbacks(execute=True):
            dataset = Dataset.objects.create(name="ds", path="/data/ds", type="raster")
        # ingest.py saves again right after creating, to patch in derived
        # spatial/temporal fields; that must not queue more work.
        with patch("datasets.tasks.ensure_dataset_partitions_task.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                dataset.title = "changed"
                dataset.save()
        delay.assert_not_called()

    def test_defers_until_after_commit(self):
        # The task must never look for a Dataset the transaction has not
        # committed yet.
        with patch("datasets.tasks.ensure_dataset_partitions_task.delay") as delay:
            with self.captureOnCommitCallbacks(execute=False):
                Dataset.objects.create(name="ds", path="/data/ds", type="raster")
            delay.assert_not_called()


class EnsureDatasetPartitionsTaskTests(TestCase):
    def test_creates_partitions_for_a_real_dataset(self):
        from datasets.tasks import ensure_dataset_partitions_task

        dataset = Dataset.objects.create(name="ds", path="/data/ds", type="raster")
        created = ensure_dataset_partitions_task(dataset.id)
        self.assertEqual(
            sorted(created),
            sorted(partition_name(p, dataset.id) for p in PARTITIONED_PARENTS),
        )

    def test_does_nothing_for_a_dataset_that_no_longer_exists(self):
        # The id travels in a message and can outlive the Dataset. A
        # partition keyed on the id alone would be created regardless,
        # leaving an orphan nothing cleans up.
        from datasets.tasks import ensure_dataset_partitions_task

        dataset = Dataset.objects.create(name="ds", path="/data/ds", type="raster")
        stale_id = dataset.id
        dataset.delete()
        self.assertEqual(ensure_dataset_partitions_task(stale_id), [])
        for parent in PARTITIONED_PARENTS:
            self.assertFalse(_exists(partition_name(parent, stale_id)))


class PartitionLockTimeoutTests(TransactionTestCase):
    """A blocked DDL has to give up, not queue.

    ACCESS EXCLUSIVE queues ahead of the statements arriving behind it, so a
    partition create left waiting on a conflicting lock stalls every claim in
    the fleet, not just itself. Giving up is the whole safety property, since
    the DEFAULT partition keeps accepting rows either way.

    Needs TransactionTestCase for a genuine second connection to hold the
    conflicting lock.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(name="ds", path="/data/ds", type="raster")

    def test_gives_up_gracefully_while_the_parent_is_locked(self):
        holding = threading.Event()
        release = threading.Event()

        def hold_access_exclusive():
            try:
                with transaction.atomic():
                    with connections["default"].cursor() as cursor:
                        cursor.execute("LOCK TABLE extract_tasks IN ACCESS EXCLUSIVE MODE")
                        holding.set()
                        release.wait(timeout=30)
            finally:
                connections["default"].close()

        thread = threading.Thread(target=hold_access_exclusive)
        thread.start()
        try:
            self.assertTrue(holding.wait(timeout=10), "lock holder never started")
            created = ensure_dataset_partitions(self.dataset.id, lock_timeout="200ms")
        finally:
            release.set()
            thread.join(timeout=30)

        # Neither partition is created, and nothing is raised. Both, not just
        # extract_tasks: extract_data's partition has to inherit the FK to
        # extract_tasks, which needs a lock on extract_tasks too, so the held
        # lock blocks both parents. (The converse also holds -- creating an
        # extract_tasks partition takes SHARE ROW EXCLUSIVE on extract_data.)
        self.assertEqual(created, [])
        # Still reported as outstanding, so a retry knows work is left.
        self.assertEqual(
            sorted(c for _, c in missing_partitions(self.dataset.id)),
            sorted(partition_name(p, self.dataset.id) for p in PARTITIONED_PARENTS),
        )

    def test_succeeds_once_the_lock_is_released(self):
        # The same call that gave up above must work unchanged afterwards --
        # giving up leaves no residue that would block a retry.
        self.assertEqual(
            sorted(ensure_dataset_partitions(self.dataset.id, lock_timeout="200ms")),
            sorted(partition_name(p, self.dataset.id) for p in PARTITIONED_PARENTS),
        )

    def tearDown(self):
        # TransactionTestCase commits, so partitions created here are real and
        # have to be removed. DETACH before DROP: while a partition is
        # attached, the inherited extract_data/request_map FK constraints
        # depend on it and a bare DROP is refused.
        with connection.cursor() as cursor:
            for parent in ("extract_data", "extract_tasks"):
                child = partition_name(parent, self.dataset.id)
                if not _exists(child):
                    continue
                cursor.execute(f'ALTER TABLE "{parent}" DETACH PARTITION "{child}"')
                cursor.execute(f'DROP TABLE "{child}"')
