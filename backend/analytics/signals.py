from celery import chain
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Request


@receiver(post_save, sender=Request)
def on_request_submitted(_sender, instance, created, **_kwargs):
    if not created:
        return
    from analytics.tasks.maintenance import process_user_requests, dispatch_processing_tasks
    chain(process_user_requests.s(), dispatch_processing_tasks.s()).delay()