import os
import runpy
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from django.contrib.gis.geos import Point
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from analytics.management.commands.build_extract_tasks import _build_extract_tasks, _build_global_tasks
from analytics.models import Coverage, ExtractTask, ExtractTaskBuildProgress, ProcessingOption
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection


class BuildExtractTasksGroupingTest(TransactionTestCase):
    def _make_feature_and_fm(self, name="fc1"):
        fc = FeatureCollection.objects.create(
            name=name, path=f"/data/{name}", active=True, is_user_upload=False
        )
        feat = Feature.objects.create(shape=Point(0, 0))
        return FeatMap.objects.create(fc=fc, geom=feat)

    def test_standard_dataset_one_task_per_resource(self):
        d = Dataset.objects.create(
            name="std_ds", path="/data/std_ds", active=True, is_global=True, task_group_period=None
        )
        po = ProcessingOption.objects.create(
            dataset=d, short_name="mean", function="rasterstats_default_mean", active=True
        )
        r1 = DatasetResource.objects.create(
            dataset=d, name="std_ds-r1", path="r1.tif", temporal=datetime(2020, 1, 1, tzinfo=timezone.utc)
        )
        r2 = DatasetResource.objects.create(
            dataset=d, name="std_ds-r2", path="r2.tif", temporal=datetime(2020, 2, 1, tzinfo=timezone.utc)
        )
        self._make_feature_and_fm()

        _build_extract_tasks()

        tasks = list(ExtractTask.objects.filter(dataset_id=d.id, po=po))
        self.assertEqual(len(tasks), 2)
        resource_id_sets = {tuple(t.resource_ids) for t in tasks}
        self.assertEqual(resource_id_sets, {(r1.id,), (r2.id,)})
        for t in tasks:
            self.assertEqual(t.dataset_id, d.id)
            self.assertIsNone(t.task_group_period)

    def test_grouped_dataset_one_task_per_year_bucket(self):
        d = Dataset.objects.create(
            name="grp_ds", path="/data/grp_ds", active=True, is_global=True, task_group_period="year"
        )
        po = ProcessingOption.objects.create(
            dataset=d, short_name="mean", function="rasterstats_default_mean", active=True
        )
        resources_2020 = [
            DatasetResource.objects.create(
                dataset=d,
                name=f"grp_ds-2020-{m:02d}",
                path=f"2020-{m:02d}.tif",
                temporal=datetime(2020, m, 1, tzinfo=timezone.utc),
            )
            for m in range(1, 13)
        ]
        resources_2021 = [
            DatasetResource.objects.create(
                dataset=d,
                name=f"grp_ds-2021-{m:02d}",
                path=f"2021-{m:02d}.tif",
                temporal=datetime(2021, m, 1, tzinfo=timezone.utc),
            )
            for m in range(1, 13)
        ]
        self._make_feature_and_fm(name="fc2")

        _build_extract_tasks()

        tasks = list(ExtractTask.objects.filter(dataset_id=d.id, po=po))
        self.assertEqual(len(tasks), 2)
        by_size = sorted(len(t.resource_ids) for t in tasks)
        self.assertEqual(by_size, [12, 12])
        all_ids = sorted(rid for t in tasks for rid in t.resource_ids)
        expected_ids = sorted(r.id for r in resources_2020 + resources_2021)
        self.assertEqual(all_ids, expected_ids)
        for t in tasks:
            self.assertEqual(t.resource_ids, sorted(t.resource_ids))
            self.assertEqual(t.task_group_period, "year")
            self.assertEqual(t.dataset_id, d.id)

    def test_non_global_dataset_one_task_per_resource(self):
        d = Dataset.objects.create(
            name="nonglobal_ds", path="/data/nonglobal_ds", active=True, is_global=False, task_group_period=None
        )
        po = ProcessingOption.objects.create(
            dataset=d, short_name="mean", function="rasterstats_default_mean", active=True
        )
        r1 = DatasetResource.objects.create(
            dataset=d, name="nonglobal_ds-r1", path="r1.tif", temporal=datetime(2020, 1, 1, tzinfo=timezone.utc)
        )
        r2 = DatasetResource.objects.create(
            dataset=d, name="nonglobal_ds-r2", path="r2.tif", temporal=datetime(2020, 2, 1, tzinfo=timezone.utc)
        )
        fm = self._make_feature_and_fm(name="fc4")
        Coverage.objects.create(geom=fm.geom, dataset=d, status=1)

        _build_extract_tasks()

        tasks = list(ExtractTask.objects.filter(dataset_id=d.id, po=po))
        self.assertEqual(len(tasks), 2)
        resource_id_sets = {tuple(t.resource_ids) for t in tasks}
        self.assertEqual(resource_id_sets, {(r1.id,), (r2.id,)})
        for t in tasks:
            self.assertEqual(t.dataset_id, d.id)
            self.assertIsNone(t.task_group_period)

    def test_claiming_prevents_duplicate_tasks_on_rerun(self):
        d = Dataset.objects.create(
            name="rerun_ds", path="/data/rerun_ds", active=True, is_global=True, task_group_period=None
        )
        po = ProcessingOption.objects.create(
            dataset=d, short_name="mean", function="rasterstats_default_mean", active=True
        )
        DatasetResource.objects.create(
            dataset=d, name="rerun_ds-r1", path="r1.tif", temporal=datetime(2020, 1, 1, tzinfo=timezone.utc)
        )
        self._make_feature_and_fm(name="fc3")

        _build_extract_tasks()
        _build_extract_tasks()

        tasks = list(ExtractTask.objects.filter(dataset_id=d.id, po=po))
        self.assertEqual(len(tasks), 1)

    def test_a_task_with_kwargs_does_not_hide_the_default_task(self):
        """A request can create a task with custom kwargs for the same
        (fm, po, resources). It is a different task, so the builder must
        still create the default (kwargs IS NULL) one beside it."""
        d = Dataset.objects.create(
            name="kwargs_ds", path="/data/kwargs_ds", active=True, is_global=True, task_group_period=None
        )
        po = ProcessingOption.objects.create(
            dataset=d, short_name="mean", function="rasterstats_default_mean", active=True
        )
        r1 = DatasetResource.objects.create(
            dataset=d, name="kwargs_ds-r1", path="r1.tif", temporal=datetime(2020, 1, 1, tzinfo=timezone.utc)
        )
        fm = self._make_feature_and_fm(name="fc5")
        ExtractTask.objects.create(
            dataset_id=d.id, resource_ids=[r1.id], fm=fm, po=po, kwargs={"categories": [1, 2]}
        )

        _build_extract_tasks()

        tasks = ExtractTask.objects.filter(dataset_id=d.id, po=po, fm=fm)
        self.assertEqual(tasks.filter(kwargs__isnull=True).count(), 1)
        self.assertEqual(tasks.filter(kwargs__isnull=False).count(), 1)

    def test_a_task_with_kwargs_does_not_hide_the_default_non_global_task(self):
        d = Dataset.objects.create(
            name="kwargs_ng_ds", path="/data/kwargs_ng_ds", active=True, is_global=False, task_group_period=None
        )
        po = ProcessingOption.objects.create(
            dataset=d, short_name="mean", function="rasterstats_default_mean", active=True
        )
        r1 = DatasetResource.objects.create(
            dataset=d, name="kwargs_ng_ds-r1", path="r1.tif", temporal=datetime(2020, 1, 1, tzinfo=timezone.utc)
        )
        fm = self._make_feature_and_fm(name="fc6")
        Coverage.objects.create(geom=fm.geom, dataset=d, status=1)
        ExtractTask.objects.create(
            dataset_id=d.id, resource_ids=[r1.id], fm=fm, po=po, kwargs={"categories": [1, 2]}
        )

        _build_extract_tasks()

        tasks = ExtractTask.objects.filter(dataset_id=d.id, po=po, fm=fm)
        self.assertEqual(tasks.filter(kwargs__isnull=True).count(), 1)
        self.assertEqual(tasks.filter(kwargs__isnull=False).count(), 1)

    def test_claim_is_touched_per_pair_before_its_own_batch_runs(self):
        """claimed_at must be refreshed as each pair's own batch starts, not
        left at whenever the whole page was claimed -- otherwise a pair late
        in a slow worker's page looks stale to other workers long before its
        own worker actually reaches it, and two workers race to insert the
        same rows (see _TOUCH_CLAIM_SQL's docstring for the production
        incident this closes).
        """
        d = Dataset.objects.create(
            name="touch_ds", path="/data/touch_ds", active=True, is_global=True, task_group_period=None
        )
        po = ProcessingOption.objects.create(
            dataset=d, short_name="mean", function="rasterstats_default_mean", active=True
        )
        DatasetResource.objects.create(
            dataset=d, name="touch_ds-r1", path="r1.tif", temporal=datetime(2020, 1, 1, tzinfo=timezone.utc)
        )

        # First pass (no feat_map rows exist yet) creates the progress-pair
        # row via the sync queries and immediately marks it caught up (0
        # candidates found, which is still "< batch_size"). Creating the
        # feature afterward gives the second, captured pass a genuinely new
        # fm_id beyond completed_up_to_fm_id -- real work for its own
        # claim+touch+batch cycle to do, which is what this test needs to
        # observe.
        _build_extract_tasks()
        pair = ExtractTaskBuildProgress.objects.get(po_id=po.id)
        self.assertIsNone(pair.claimed_at)

        self._make_feature_and_fm(name="fc-touch")

        with CaptureQueriesContext(connection) as ctx:
            _build_global_tasks()

        claim_idx = touch_idx = insert_idx = None
        for i, q in enumerate(ctx.captured_queries):
            sql = q["sql"]
            # Raw SQL executed via connection.cursor(), not the ORM -- no
            # quoted identifiers, unlike Django-generated queries.
            is_claimed_at_update = (
                "UPDATE extract_task_build_progress" in sql
                and "claimed_at = NOW()" in sql
            )
            if is_claimed_at_update and "ANY(" in sql:
                claim_idx = i  # pages the whole round's pairs in one UPDATE
            elif is_claimed_at_update and f"WHERE id = {pair.id}" in sql:
                touch_idx = i  # per-pair touch, keyed on this exact id
            elif "INSERT INTO extract_tasks" in sql and insert_idx is None:
                insert_idx = i  # this pair's own batch (first INSERT after its touch)

        self.assertIsNotNone(claim_idx, "expected the page-claim UPDATE to run")
        self.assertIsNotNone(touch_idx, "expected a per-pair touch UPDATE keyed on this pair's id")
        self.assertIsNotNone(insert_idx, "expected the batch INSERT for this pair to run")
        self.assertLess(claim_idx, touch_idx, "per-pair touch must come after the page-claim")
        self.assertLess(touch_idx, insert_idx, "per-pair touch must come before that pair's own batch runs")


class BuildRunDispatchGuardTest(TransactionTestCase):
    """The run guard makes frequent build triggers safe.

    Healthy waves reject overlapping launches. Finished/capped waves release
    the guard when their last worker exits; interrupted waves recover through
    the stale heartbeat and a later trigger. The defaults trigger every ten
    minutes, and operators can choose a different cadence.
    """

    def set_run(self, *, in_progress, minutes_ago):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO extract_task_build_run (id, in_progress, last_progress_at)
                VALUES (1, %s, NOW() - (%s || ' minutes')::interval)
                ON CONFLICT (id) DO UPDATE
                SET in_progress = EXCLUDED.in_progress,
                    last_progress_at = EXCLUDED.last_progress_at
                """,
                [in_progress, str(minutes_ago)],
            )

    def test_a_live_wave_is_not_duplicated(self):
        from analytics.tasks import maintenance

        self.set_run(in_progress=True, minutes_ago=1)

        with mock.patch.object(
            maintenance.build_extract_tasks_worker, "delay"
        ) as delay:
            maintenance.build_extract_tasks()

        delay.assert_not_called()

    def test_a_dead_wave_is_restarted(self):
        # A crashed worker never decrements workers_remaining. The next
        # trigger after the heartbeat goes stale must still launch a new wave.
        from analytics.management.commands.build_extract_tasks import (
            RUN_STALE_MINUTES,
        )
        from analytics.tasks import maintenance

        self.set_run(in_progress=True, minutes_ago=RUN_STALE_MINUTES + 5)

        with mock.patch.object(
            maintenance.build_extract_tasks_worker, "delay"
        ) as delay:
            maintenance.build_extract_tasks()

        self.assertEqual(delay.call_count, maintenance._n_extract_task_builders())

    def test_an_idle_run_lock_dispatches(self):
        from analytics.tasks import maintenance

        self.set_run(in_progress=False, minutes_ago=1)

        with mock.patch.object(
            maintenance.build_extract_tasks_worker, "delay"
        ) as delay:
            maintenance.build_extract_tasks()

        self.assertEqual(delay.call_count, maintenance._n_extract_task_builders())

    def test_builder_parallelism_is_configurable(self):
        # Each worker holds a pooler connection for an 11-20s INSERT batch,
        # so this is the knob that trades build-out speed for extract
        # throughput. Tunable by env var, no deploy needed.
        from analytics.tasks import maintenance

        self.set_run(in_progress=False, minutes_ago=1)

        with (
            mock.patch.object(maintenance.build_extract_tasks_worker, "delay") as delay,
            self.settings(N_EXTRACT_TASK_BUILDERS=5),
        ):
            maintenance.build_extract_tasks()

        self.assertEqual(delay.call_count, 5)

    def test_builder_parallelism_never_drops_below_one(self):
        # A 0 would silently stop building altogether rather than slow it.
        from analytics.tasks import maintenance

        self.set_run(in_progress=False, minutes_ago=1)

        with (
            mock.patch.object(maintenance.build_extract_tasks_worker, "delay") as delay,
            self.settings(N_EXTRACT_TASK_BUILDERS=0),
        ):
            maintenance.build_extract_tasks()

        self.assertEqual(delay.call_count, 1)

    def test_only_the_last_worker_releases_a_capped_wave(self):
        from analytics.management.commands import build_extract_tasks as cmd
        from analytics.models import ExtractTaskBuildRun
        from analytics.tasks import maintenance

        self.set_run(in_progress=False, minutes_ago=1)
        run_id = cmd.try_acquire_build_run(worker_count=2)
        with mock.patch.object(cmd, "_build_global_tasks", return_value=3):
            maintenance.build_extract_tasks_worker(run_id=str(run_id))
            run = ExtractTaskBuildRun.objects.get(id=1)
            self.assertTrue(run.in_progress)
            self.assertEqual(run.workers_remaining, 1)
            self.assertIsNone(cmd.try_acquire_build_run(worker_count=2))
            maintenance.build_extract_tasks_worker(run_id=str(run_id))

        run.refresh_from_db()
        self.assertFalse(run.in_progress)
        self.assertEqual(run.workers_remaining, 0)
        self.assertIsNotNone(cmd.try_acquire_build_run(worker_count=2))

    def test_a_late_worker_cannot_finish_or_heartbeat_a_replacement_wave(self):
        from analytics.management.commands import build_extract_tasks as cmd
        from analytics.models import ExtractTaskBuildRun

        self.set_run(in_progress=False, minutes_ago=1)
        old_run_id = cmd.try_acquire_build_run(worker_count=2)
        self.set_run(in_progress=True, minutes_ago=cmd.RUN_STALE_MINUTES + 1)
        new_run_id = cmd.try_acquire_build_run(worker_count=2)
        self.assertNotEqual(old_run_id, new_run_id)

        cmd.finish_build_worker(old_run_id)
        self.assertFalse(cmd._heartbeat_build_run(old_run_id))
        run = ExtractTaskBuildRun.objects.get(id=1)
        self.assertTrue(run.in_progress)
        self.assertEqual(run.workers_remaining, 2)
        self.assertEqual(run.run_id, new_run_id)

    def test_a_failed_worker_releases_its_wave_slot(self):
        from analytics.management.commands import build_extract_tasks as cmd
        from analytics.models import ExtractTaskBuildRun
        from analytics.tasks import maintenance

        self.set_run(in_progress=False, minutes_ago=1)
        run_id = cmd.try_acquire_build_run()
        with mock.patch.object(cmd, "_build_global_tasks", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                maintenance.build_extract_tasks_worker(run_id=str(run_id))
        self.assertFalse(ExtractTaskBuildRun.objects.get(id=1).in_progress)


class BuildBeatScheduleTest(TransactionTestCase):
    def test_build_extract_tasks_uses_the_configured_interval(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["build-extract-tasks"]
        self.assertEqual(
            entry["task"], "analytics.tasks.maintenance.build_extract_tasks"
        )

        self.assertGreaterEqual(entry["schedule"], 1)
        self.assertEqual(entry["schedule"], settings.EXTRACT_TASK_BUILD_INTERVAL_SECONDS)

    def test_result_backend_cleanup_is_scheduled(self):
        # Without this entry nothing prunes django_celery_results_taskresult;
        # it had reached 2.8M rows / 4.4GB in 43 hours unbounded.
        from django.conf import settings

        self.assertIn("celery-backend-cleanup", settings.CELERY_BEAT_SCHEDULE)
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["celery-backend-cleanup"]["task"],
            "celery.backend_cleanup",
        )
        self.assertGreater(settings.CELERY_RESULT_EXPIRES, 0)


class BuildBatchCommitModeTest(TransactionTestCase):
    """Build batches commit asynchronously; nothing else does.

    The database is write-bandwidth bound -- backends queue on the WALWrite
    lock -- and these 5000-row batches are the largest single contributor.
    Taking them out of the fsync path frees storage bandwidth the processing
    path also needs. Safe only because the rows are speculative: a crash
    loses at most ~200ms of them and completed_up_to_fm_id will not have
    advanced, so the next pass rebuilds exactly what was lost.
    """

    def captured_sql(self):
        from analytics.management.commands import build_extract_tasks as cmd

        with CaptureQueriesContext(connection) as ctx:
            cmd._run_batch("SELECT 1 WHERE false", [])
        return [q["sql"] for q in ctx.captured_queries]

    def test_batches_commit_asynchronously_by_default(self):
        self.assertTrue(
            any("synchronous_commit = off" in q for q in self.captured_sql()),
            "build batches should not wait for fsync",
        )

    def test_it_is_scoped_to_the_transaction_not_the_session(self):
        # SET LOCAL, not SET: a plain SET would leak to every later query on
        # the same pooled connection, silently making unrelated writes
        # non-durable.
        sql = [q for q in self.captured_sql() if "synchronous_commit" in q]
        self.assertTrue(sql)
        for q in sql:
            self.assertIn("SET LOCAL", q, f"must be transaction-scoped: {q}")

    def test_synchronous_commit_can_be_restored_without_a_deploy(self):
        with self.settings(EXTRACT_TASK_BUILD_SYNCHRONOUS_COMMIT=True):
            self.assertFalse(
                any("synchronous_commit" in q for q in self.captured_sql()),
                "setting must restore default (synchronous) commits",
            )


class BuildProgressWatermarkTest(TransactionTestCase):
    """Each batch records how far it got, not just the batch that finishes a pair.

    completed_up_to_fm_id used to advance only when a pair ran out of work
    (added < batch_size). A pair returning full batches recorded nothing, so
    every batch restarted at fm.id > 0 and re-walked everything it had already
    built -- cost growing with what was done rather than what was left, which
    is what this table exists to prevent. Measured on production against a
    pair with 695k rows built: 53,248ms and 169.7M buffer hits to find the
    next 5,000 rows, versus 621ms and 724k hits resuming from the watermark.
    """

    def _dataset_with_one_resource(self, name):
        d = Dataset.objects.create(
            name=name, path=f"/data/{name}", active=True, is_global=True, task_group_period=None
        )
        ProcessingOption.objects.create(
            dataset=d, short_name="mean", function="rasterstats_default_mean", active=True
        )
        DatasetResource.objects.create(
            dataset=d, name=f"{name}-r1", path="r1.tif",
            temporal=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        return d

    def _make_fms(self, count, name="fc-wm"):
        fc = FeatureCollection.objects.create(
            name=name, path=f"/data/{name}", active=True, is_user_upload=False
        )
        return [
            FeatMap.objects.create(fc=fc, geom=Feature.objects.create(shape=Point(0, 0)))
            for _ in range(count)
        ]

    def _pair_for(self, dataset):
        """Create the progress row the way a real run does, without building."""
        from analytics.management.commands import build_extract_tasks as cmd

        with connection.cursor() as cursor:
            cursor.execute(cmd._SYNC_STANDARD_PAIRS_SQL)
        return ExtractTaskBuildProgress.objects.get(po__dataset_id=dataset.id)

    def _run_one_batch(self, dataset, pair, batch_size, start_from):
        """One batch of exactly the statement production runs.

        Driven directly rather than through _build_global_tasks because that
        loops until every pair is exhausted, so a whole-run assertion can only
        ever see the finished state -- never the mid-flight watermark this
        class is about.
        """
        from analytics.management.commands import build_extract_tasks as cmd

        po = ProcessingOption.objects.get(dataset_id=dataset.id)
        resource = DatasetResource.objects.get(dataset_id=dataset.id)
        return cmd._run_batch(
            cmd._INSERT_GLOBAL_BATCH_SQL,
            {
                "dataset_id": dataset.id,
                "resource_ids": [resource.id],
                "task_group_period": None,
                "po_id": po.id,
                "completed_up_to_fm_id": start_from,
                "batch_size": batch_size,
                "progress_id": pair.id,
            },
            fetch=True,
        )

    def test_a_full_batch_records_how_far_it_got(self):
        # The regression this class exists for: a pair with more work left
        # than one batch must still record progress, or the next batch
        # rescans everything it already built.
        d = self._dataset_with_one_resource("wm_full")
        fms = self._make_fms(3)
        pair = self._pair_for(d)

        added, max_fm_id = self._run_one_batch(d, pair, batch_size=2, start_from=0)
        pair.refresh_from_db()

        self.assertEqual(added, 2, "batch_size should have capped this batch")
        self.assertEqual(max_fm_id, fms[1].id)
        self.assertEqual(
            pair.completed_up_to_fm_id, max_fm_id,
            "watermark must advance to the last row the batch actually inserted",
        )
        self.assertLess(
            pair.completed_up_to_fm_id, fms[-1].id,
            "the pair is not finished, so the watermark must not jump past unbuilt rows",
        )

    def test_the_next_batch_resumes_from_the_watermark(self):
        d = self._dataset_with_one_resource("wm_resume")
        fms = self._make_fms(3)
        pair = self._pair_for(d)

        self._run_one_batch(d, pair, batch_size=2, start_from=0)
        pair.refresh_from_db()
        added, _ = self._run_one_batch(
            d, pair, batch_size=2, start_from=pair.completed_up_to_fm_id
        )

        self.assertEqual(added, 1, "only the one unbuilt row should remain")
        self.assertEqual(
            sorted(ExtractTask.objects.filter(dataset_id=d.id).values_list("fm_id", flat=True)),
            sorted(f.id for f in fms),
            "resuming must add to what the first batch built, not redo or skip it",
        )

    def test_a_partial_batch_still_marks_the_pair_caught_up(self):
        # Unchanged behaviour: a pair that runs out of work jumps to the
        # current max fm_id, which covers the tail where there was nothing to
        # do -- beyond the last row it actually inserted.
        d = self._dataset_with_one_resource("wm_partial")
        fms = self._make_fms(2)

        _build_extract_tasks(batch_size=50)

        pair = ExtractTaskBuildProgress.objects.get(po__dataset_id=d.id)
        self.assertGreaterEqual(pair.completed_up_to_fm_id, fms[-1].id)
        self.assertIsNone(pair.claimed_at, "a caught-up pair must release its claim")

    def test_a_batch_that_inserts_nothing_leaves_the_watermark_alone(self):
        # GREATEST/IS NOT NULL guard: an empty batch must not reset a
        # watermark to 0 or stall a pair by moving it backwards.
        d = self._dataset_with_one_resource("wm_empty")
        self._make_fms(2)

        _build_extract_tasks(batch_size=50)
        pair = ExtractTaskBuildProgress.objects.get(po__dataset_id=d.id)
        before = pair.completed_up_to_fm_id

        _build_extract_tasks(batch_size=50)
        pair.refresh_from_db()

        self.assertEqual(pair.completed_up_to_fm_id, before)
        self.assertEqual(ExtractTask.objects.filter(dataset_id=d.id).count(), 2)

    def test_a_capped_worker_trims_the_last_batch_and_resumes(self):
        d = self._dataset_with_one_resource("capped")
        fms = self._make_fms(8)

        with self.settings(EXTRACT_TASK_BUILD_BATCH_SIZE=3, EXTRACT_TASK_BUILD_MAX_TASKS=5):
            self.assertEqual(_build_global_tasks(), 5)
            pair = ExtractTaskBuildProgress.objects.get(po__dataset_id=d.id)
            self.assertEqual(pair.completed_up_to_fm_id, fms[4].id)
            self.assertIsNone(pair.claimed_at)
            self.assertEqual(_build_global_tasks(), 3)

        self.assertEqual(ExtractTask.objects.filter(dataset_id=d.id).count(), 8)
        pair.refresh_from_db()
        self.assertEqual(pair.completed_up_to_fm_id, fms[-1].id)

    def test_a_cap_smaller_than_one_batch_releases_unstarted_pairs(self):
        d = self._dataset_with_one_resource("small_cap")
        DatasetResource.objects.create(
            dataset=d, name="small_cap-r2", path="r2.tif",
            temporal=datetime(2021, 1, 1, tzinfo=timezone.utc),
        )
        self._make_fms(4)

        self.assertEqual(_build_global_tasks(batch_size=5, max_tasks=2), 2)
        pairs = ExtractTaskBuildProgress.objects.filter(po__dataset_id=d.id)
        self.assertEqual(pairs.count(), 2)
        self.assertFalse(pairs.filter(claimed_at__isnull=False).exists())
        self.assertEqual(_build_global_tasks(batch_size=5, max_tasks=0), 6)
        self.assertEqual(ExtractTask.objects.filter(dataset_id=d.id).count(), 8)

    def test_preexisting_tasks_do_not_consume_the_worker_budget(self):
        d = self._dataset_with_one_resource("existing_cap")
        fms = self._make_fms(5)
        po = ProcessingOption.objects.get(dataset_id=d.id)
        resource = DatasetResource.objects.get(dataset_id=d.id)
        ExtractTask.objects.create(dataset_id=d.id, resource_ids=[resource.id], fm=fms[0], po=po)

        self.assertEqual(_build_global_tasks(batch_size=3, max_tasks=2), 2)
        self.assertEqual(ExtractTask.objects.filter(dataset_id=d.id).count(), 3)

    def test_non_global_workers_also_obey_the_cap(self):
        from analytics.management.commands.build_extract_tasks import _build_non_global_tasks

        d = self._dataset_with_one_resource("non_global_cap")
        d.is_global = False
        d.save(update_fields=["is_global"])
        for fm in self._make_fms(8):
            Coverage.objects.create(dataset=d, geom=fm.geom, status=1)

        with self.settings(EXTRACT_TASK_BUILD_BATCH_SIZE=3, EXTRACT_TASK_BUILD_MAX_TASKS=5):
            self.assertEqual(_build_non_global_tasks(), 5)
            self.assertEqual(_build_non_global_tasks(), 3)
        self.assertEqual(ExtractTask.objects.filter(dataset_id=d.id).count(), 8)

    def test_the_management_command_shares_one_budget_across_both_branches(self):
        global_ds = self._dataset_with_one_resource("shared_global")
        non_global_ds = self._dataset_with_one_resource("shared_non_global")
        non_global_ds.is_global = False
        non_global_ds.save(update_fields=["is_global"])
        for fm in self._make_fms(2):
            Coverage.objects.create(dataset=non_global_ds, geom=fm.geom, status=1)

        with self.settings(EXTRACT_TASK_BUILD_BATCH_SIZE=2, EXTRACT_TASK_BUILD_MAX_TASKS=3):
            self.assertEqual(_build_extract_tasks()["added"], 3)
        self.assertEqual(ExtractTask.objects.filter(dataset_id=global_ds.id).count(), 2)
        self.assertEqual(ExtractTask.objects.filter(dataset_id=non_global_ds.id).count(), 1)

    def test_a_superseded_worker_does_not_build_any_tasks(self):
        from analytics.management.commands import build_extract_tasks as cmd
        from uuid import uuid4

        d = self._dataset_with_one_resource("old_worker")
        self._make_fms(3)
        self.assertEqual(_build_global_tasks(run_id=uuid4()), 0)
        self.assertFalse(ExtractTask.objects.filter(dataset_id=d.id).exists())

    def test_unstarted_claim_cleanup_does_not_clear_a_replacement_claim(self):
        from analytics.management.commands import build_extract_tasks as cmd

        d = self._dataset_with_one_resource("claim_cleanup")
        pair = self._pair_for(d)
        with connection.cursor() as cursor:
            cursor.execute(cmd._CLAIM_PROGRESS_PAIRS_SQL, [[pair.id]])
            old_claim = cursor.fetchone()[0]
            cursor.execute(cmd._TOUCH_CLAIM_SQL, [pair.id])
        cmd._release_unstarted_claims([pair.id], old_claim)
        pair.refresh_from_db()
        self.assertIsNotNone(pair.claimed_at)

    def test_a_task_past_the_watermark_still_blocks_a_duplicate(self):
        # The existence check is bounded to fm_id > watermark. Tasks the
        # request path created past the watermark are exactly what it must
        # still find; a bound written the wrong way round would hide them.
        d = self._dataset_with_one_resource("wm_bound")
        fms = self._make_fms(3)
        pair = self._pair_for(d)
        po = ProcessingOption.objects.get(dataset_id=d.id)
        resource = DatasetResource.objects.get(dataset_id=d.id)
        ExtractTask.objects.create(dataset_id=d.id, resource_ids=[resource.id], fm=fms[2], po=po)

        added, _ = self._run_one_batch(d, pair, batch_size=50, start_from=fms[0].id)

        self.assertEqual(added, 1, "only fms[1] is past the watermark and unbuilt")
        self.assertEqual(
            sorted(ExtractTask.objects.filter(dataset_id=d.id).values_list("fm_id", flat=True)),
            [fms[1].id, fms[2].id],
        )

    def test_the_existence_check_is_bounded_by_the_watermark(self):
        """The bound is logically redundant, so no row-level assertion can
        catch its removal; what it buys is the planner seeing it. Without it,
        a pair whose rows postdate the statistics was planned as a rescan of
        everything it had built, per candidate feature -- 24-30s per batch
        against ~110ms with it, measured on a production replica.
        """
        from analytics.management.commands import build_extract_tasks as cmd

        d = self._dataset_with_one_resource("wm_plan")
        fms = self._make_fms(2)
        pair = self._pair_for(d)
        po = ProcessingOption.objects.get(dataset_id=d.id)
        resource = DatasetResource.objects.get(dataset_id=d.id)

        with connection.cursor() as cursor:
            cursor.execute(
                "EXPLAIN " + cmd._INSERT_GLOBAL_BATCH_SQL,
                {
                    "dataset_id": d.id,
                    "resource_ids": [resource.id],
                    "task_group_period": None,
                    "po_id": po.id,
                    "completed_up_to_fm_id": fms[0].id,
                    "batch_size": 50,
                    "progress_id": pair.id,
                },
            )
            plan = "\n".join(row[0] for row in cursor.fetchall())

        self.assertIn(
            f"fm_id > {fms[0].id}", plan,
            "the extract_tasks probe must carry the watermark bound itself",
        )

    def test_the_watermark_advances_in_the_same_statement_as_the_insert(self):
        """Not stylistic: _run_batch commits asynchronously, so a separately
        committed watermark could survive a crash that lost the insert, and
        those feat_map rows would be skipped forever with nothing to notice.
        One statement means they are lost or kept together.
        """
        self._dataset_with_one_resource("wm_atomic")
        self._make_fms(3)

        with CaptureQueriesContext(connection) as ctx:
            _build_global_tasks(batch_size=2)

        inserts = [
            q["sql"] for q in ctx.captured_queries
            if "INSERT INTO extract_tasks" in q["sql"]
        ]
        self.assertTrue(inserts, "expected the batch INSERT to run")
        for sql in inserts:
            self.assertIn(
                "UPDATE extract_task_build_progress", sql,
                "the watermark UPDATE must live inside the INSERT's own statement",
            )


class BuildEnvironmentSettingsTest(SimpleTestCase):
    def load_settings(self, **env):
        with mock.patch.dict(os.environ, env):
            return runpy.run_path(str(Path(__file__).resolve().parents[2] / "geoquery" / "settings.py"))

    def test_environment_controls_the_schedule_and_limits(self):
        config = self.load_settings(
            EXTRACT_TASK_BUILD_INTERVAL_SECONDS="125",
            EXTRACT_TASK_BUILD_BATCH_SIZE="7",
            EXTRACT_TASK_BUILD_MAX_TASKS="19",
        )
        self.assertEqual(config["CELERY_BEAT_SCHEDULE"]["build-extract-tasks"]["schedule"], 125)
        self.assertEqual(config["EXTRACT_TASK_BUILD_BATCH_SIZE"], 7)
        self.assertEqual(config["EXTRACT_TASK_BUILD_MAX_TASKS"], 19)

    def test_default_build_schedule_preserves_the_recovery_budget(self):
        """Protect the default ~20-minute crash-recovery budget.

        On 2026-09-24 a wave died at 00:07, became claimable at 00:37,
        missed the hourly 00:30 trigger, and resumed at 01:30: 83 minutes
        idle. Recovery needs both expired claims and another trigger.

        This checks the shipped defaults independently of environment
        overrides. Operators may intentionally choose slower triggers; queue
        and process startup delays are outside this scheduling budget.
        """
        from analytics.management.commands.build_extract_tasks import (
            CLAIM_STALE_MINUTES,
            RUN_STALE_MINUTES,
        )

        with mock.patch.dict(os.environ):
            for name in (
                "EXTRACT_TASK_BUILD_INTERVAL_SECONDS",
                "EXTRACT_TASK_BUILD_BATCH_SIZE",
                "EXTRACT_TASK_BUILD_MAX_TASKS",
            ):
                os.environ.pop(name, None)
            config = self.load_settings()

        interval = config["CELERY_BEAT_SCHEDULE"]["build-extract-tasks"]["schedule"]
        stale_seconds = max(CLAIM_STALE_MINUTES, RUN_STALE_MINUTES) * 60
        self.assertLessEqual(stale_seconds + interval, 20 * 60)

    def test_operators_can_choose_a_longer_interval_and_larger_batches(self):
        config = self.load_settings(
            EXTRACT_TASK_BUILD_INTERVAL_SECONDS="3600",
            EXTRACT_TASK_BUILD_BATCH_SIZE="100000",
            EXTRACT_TASK_BUILD_MAX_TASKS="300000",
        )
        self.assertEqual(config["CELERY_BEAT_SCHEDULE"]["build-extract-tasks"]["schedule"], 3600)
        self.assertEqual(config["EXTRACT_TASK_BUILD_BATCH_SIZE"], 100000)
        self.assertEqual(config["EXTRACT_TASK_BUILD_MAX_TASKS"], 300000)

    def test_invalid_limits_are_rejected_at_startup(self):
        for name, value in (
            ("EXTRACT_TASK_BUILD_INTERVAL_SECONDS", "0"),
            ("EXTRACT_TASK_BUILD_BATCH_SIZE", "0"),
            ("EXTRACT_TASK_BUILD_MAX_TASKS", "-1"),
        ):
            with self.subTest(name=name), self.assertRaisesMessage(ImproperlyConfigured, name):
                self.load_settings(**{name: value})
