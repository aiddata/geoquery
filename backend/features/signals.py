from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FeatureCollection


# @receiver(post_save, sender=FeatureCollection)
# def on_feature_collection_saved(sender, instance, **kwargs):
#     if instance.is_user_upload:
#         return
#     from features.matviews import refresh_materialized_views
#     refresh_materialized_views()
