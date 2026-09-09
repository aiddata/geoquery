from django.db import IntegrityError
from django.test import TestCase
from datasets.models import Dataset


class DatasetTaskGroupPeriodTest(TestCase):
    def test_default_is_none(self):
        d = Dataset.objects.create(
            name="test_ds_ungrouped",
            active=True,
            path="test_ds_ungrouped",
            type="raster",
        )
        self.assertIsNone(d.task_group_period)

    def test_accepts_valid_periods(self):
        # is_global=True is required alongside task_group_period -- see
        # dataset_task_group_period_requires_global, added after this test:
        # build_extract_tasks only checks task_group_period on the is_global
        # branch, so a non-global grouped dataset would silently build zero
        # tasks forever.
        for period in ("day", "week", "month", "quarter", "year"):
            d = Dataset.objects.create(
                name=f"test_ds_{period}",
                active=True,
                path=f"test_ds_{period}",
                type="raster",
                is_global=True,
                task_group_period=period,
            )
            d.refresh_from_db()
            self.assertEqual(d.task_group_period, period)

    def test_task_group_period_requires_is_global(self):
        with self.assertRaises(IntegrityError):
            Dataset.objects.create(
                name="test_ds_non_global_grouped",
                active=True,
                path="test_ds_non_global_grouped",
                type="raster",
                is_global=False,
                task_group_period="year",
            )
