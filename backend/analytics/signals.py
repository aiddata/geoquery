from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Request


@receiver(post_save, sender=Request)
def on_request_submitted(_sender, instance, created, **_kwargs):
    if not created:
        return
    from analytics.tasks.maintenance import process_user_requests, dispatch_processing_tasks
    process_user_requests.delay()
    dispatch_processing_tasks.delay()