from io import StringIO

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import TransactionTestCase

from analytics.models import ExtractData, ExtractTask, ProcessingOption
from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature, FeatureCollection


class ResetExtractDataTest(TransactionTestCase):
    """reset_extract_data: the cutover that discards derived extract results.

    TransactionTestCase rather than TestCase because the command issues
    TRUNCATE and VACUUM, neither of which behaves inside the wrapping
    transaction TestCase would hold open for the whole test.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(name="ds", path="/data/ds", active=True)
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset, short_name="mean",
            function="rasterstats_default_mean", active=True,
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r0", path="r0.tif"
        )
        fc = FeatureCollection.objects.create(name="fc", path="/data/fc", active=True)
        self.fm = FeatMap.objects.create(
            fc=fc, geom=Feature.objects.create(shape=Point(0, 0))
        )

    def _task(self, status, po=None):
        return ExtractTask.objects.create(
            resource_ids=[self.resource.id], dataset_id=self.dataset.id,
            fm=self.fm, po=po or self.po, status=status, attempts=2,
        )

    def test_refuses_without_confirm(self):
        task = self._task(status=1)
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id,
            name="mean", float_value=1.0,
        )

        with self.assertRaises(SystemExit):
            call_command("reset_extract_data", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(ExtractData.objects.count(), 1)
        task.refresh_from_db()
        self.assertEqual(task.status, 1)

    def test_dry_run_changes_nothing(self):
        task = self._task(status=1)
        ExtractData.objects.create(
            extract_task=task, dataset_id=self.dataset.id,
            name="mean", float_value=1.0,
        )

        call_command("reset_extract_data", "--dry-run", stdout=StringIO())

        self.assertEqual(ExtractData.objects.count(), 1)
        task.refresh_from_db()
        self.assertEqual(task.status, 1)

    def test_confirm_truncates_and_resets(self):
        from django.utils import timezone

        done = self._task(status=1)
        ExtractTask.objects.filter(id=done.id).update(
            complete_time=timezone.now(), error="stale"
        )
        # Distinct po: extract_tasks_fm_po_resources_null_kwargs_idx is a
        # unique index on (dataset_id, fm_id, po_id, resource_ids) where
        # kwargs IS NULL, so a second task sharing done's fm/po/resource_ids
        # would collide -- these have to be two genuinely different tasks.
        po2 = ProcessingOption.objects.create(
            dataset=self.dataset, short_name="sum",
            function="rasterstats_default_sum", active=True,
        )
        pending = self._task(status=0, po=po2)
        ExtractData.objects.create(
            extract_task=done, dataset_id=self.dataset.id,
            name="mean", float_value=1.0,
        )

        call_command("reset_extract_data", "--confirm", stdout=StringIO())

        self.assertEqual(ExtractData.objects.count(), 0)
        done.refresh_from_db()
        self.assertEqual(done.status, 0)
        self.assertIsNone(done.complete_time)
        self.assertIsNone(done.error)
        self.assertEqual(done.attempts, 0)
        pending.refresh_from_db()
        self.assertEqual(pending.status, 0)
