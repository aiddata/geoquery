from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Feature, FeatureCollection


@receiver(post_save, sender=Feature)
def on_feature_created(sender, instance, created, **kwargs):
    if not created:
        return
    # User-upload features are created via bulk_create, which does not fire signals,
    # so no guard is needed here — this handler only runs for standard ingest.
    from analytics.tasks.coverage import create_coverage_records_for_feature, test_coverage_for_feature
    create_coverage_records_for_feature(instance.id)
    test_coverage_for_feature.delay(instance.id)


@receiver(post_save, sender=FeatureCollection)
def on_feature_collection_saved(sender, instance, **kwargs):
    if instance.is_user_upload:
        return
    from features.matviews import refresh_materialized_views
    refresh_materialized_views()