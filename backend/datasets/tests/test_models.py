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

    def test_grouped_datasets_may_be_non_global(self):
        # Pair sync groups every dataset the same way and coverage gates
        # non-global ones per feature, so the old requires-global constraint
        # (migration 0009) is gone.
        d = Dataset.objects.create(
            name="test_ds_non_global_grouped",
            active=True,
            path="test_ds_non_global_grouped",
            type="raster",
            is_global=False,
            task_group_period="year",
        )
        d.refresh_from_db()
        self.assertEqual(d.task_group_period, "year")
        self.assertFalse(d.is_global)
