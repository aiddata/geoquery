from celery import chain
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Request


@receiver(post_save, sender=Request)
def on_request_submitted(sender, instance, created, **kwargs):
    """Schedule Celery work in response to a Request's saved state.

    Two independent conditions, not an if/elif -- a Request could in
    principle satisfy both across its lifetime, just never in the same
    save (status 4 only applies at creation; status -1/0 never applies at
    creation today, since both production create-paths start at 3 or 4).

    created and status==4: the request was just submitted and needs its
    ExtractTask/RequestMap rows built in the background (see
    analytics.services.create_request / materialize_request).

    status in (-1, 0), created or not: the request just became -- or still
    is -- something the periodic completion sweep should look at right
    away rather than waiting for the next scheduled tick. This fires for
    Request.objects.create() at status=-1/0 (no current production path
    does this, but it's a safety net for any future one that does), and
    for any .save() that lands a Request on -1 or 0 -- currently
    materialize_request's status=4->-1 transition and
    ingest_custom_boundary's status=3->-1 transition, both real .save()
    calls. The completion sweep itself never triggers this: it transitions
    status exclusively via bulk .update() (manage_user_requests.py), which
    Django never turns into a post_save signal, so this cannot cascade off
    the sweep's own -1->2->0/1 progression.

    Both branches defer to transaction.on_commit so a task can never start
    working on a Request before the transaction that made it visible has
    actually committed -- required here specifically because
    materialize_request's .save() runs inside its own transaction.atomic()
    block, so this receiver executes synchronously *inside* that block.
    """
    if created and instance.status == 4:
        from analytics.tasks.requests import materialize_request_tasks

        transaction.on_commit(
            lambda: materialize_request_tasks.delay(str(instance.id))
        )

    if instance.status in (-1, 0):
        from analytics.tasks.maintenance import (
            dispatch_processing_tasks,
            process_user_requests,
        )

        transaction.on_commit(
            lambda: chain(
                process_user_requests.si(), dispatch_processing_tasks.si()
            ).delay()
        )
