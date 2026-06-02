from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Feature, FeatureCollection


@receiver(post_save, sender=Feature)
def on_feature_created(_sender, instance, created, **_kwargs):
    if not created:
        return
    from analytics.tasks.coverage import create_coverage_records_for_feature, test_coverage_for_feature
    create_coverage_records_for_feature(instance.id)
    test_coverage_for_feature.delay(instance.id)


@receiver(post_save, sender=FeatureCollection)
def on_feature_collection_saved(_sender, _instance, **_kwargs):
    from features.matviews import refresh_materialized_views
    refresh_materialized_views()