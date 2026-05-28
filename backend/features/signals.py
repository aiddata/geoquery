from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Feature


@receiver(post_save, sender=Feature)
def on_feature_created(sender, instance, created, **kwargs):
    if not created:
        return
    from analytics.tasks.coverage import create_coverage_records_for_feature
    create_coverage_records_for_feature(instance.id)