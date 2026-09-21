from datetime import datetime, timezone
from unittest import mock

from django.contrib.gis.geos import Point
from django.db import connection
from django.test import TransactionTestCase
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
    """The run-lock is what makes an hourly build beat safe.

    The beat fires hourly so a wave killed mid-flight (rolling deploy,
    eviction, OOM) resumes within the hour instead of waiting for the next
    daily tick -- the run-lock and per-pair claims expire on their own, so
    the work is claimable again, but nothing re-dispatched workers to claim
    it. Firing that often is only safe because try_acquire_build_run refuses
    to launch a second fan-out on top of a live one.
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
        # RUN_STALE_MINUTES is 30; this is the case the hourly beat exists
        # for -- workers gone, lock still flagged in_progress, nothing
        # re-dispatching them.
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


class BuildBeatScheduleTest(TransactionTestCase):
    def test_build_extract_tasks_runs_hourly(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["build-extract-tasks"]
        self.assertEqual(
            entry["task"], "analytics.tasks.maintenance.build_extract_tasks"
        )
        # crontab with only `minute` set fires every hour at that minute.
        self.assertEqual(set(entry["schedule"].hour), set(range(24)))
