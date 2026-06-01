from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Dataset


@receiver(post_save, sender=Dataset)
def on_dataset_created(_sender, instance, created, **_kwargs):
    if not created:
        return
    from analytics.tasks.coverage import create_coverage_records_for_dataset, test_coverage_for_dataset
    create_coverage_records_for_dataset(instance.id)
    test_coverage_for_dataset.delay(instance.id)