from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import FeatureCollection


@receiver(post_delete, sender=FeatureCollection)
def on_feature_collection_deleted(sender, instance, **kwargs):
    """Clear a deleted collection's rows from the simplified-geometry tables.

    Those tables carry no foreign key back to feature_collections, so the
    usual CASCADE cannot clean them up.
    """
    from features.matviews import remove_simplified_geometries

    remove_simplified_geometries(instance.id)
