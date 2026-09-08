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
                task_group_period=period,
            )
            d.refresh_from_db()
            self.assertEqual(d.task_group_period, period)
