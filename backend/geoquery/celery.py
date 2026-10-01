import os

from celery import Celery
from celery.signals import worker_init, worker_process_shutdown

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoquery.settings")

app = Celery("geoquery")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@worker_init.connect
def start_metrics_exporter(**kwargs):
    # Fires once in the parent process, before the pool forks, which is the
    # one process that lives as long as the worker does.
    from django.conf import settings

    from analytics.metrics import start_worker_exporter

    start_worker_exporter(settings.WORKER_METRICS_PORT)


@worker_process_shutdown.connect
def forget_exited_child(pid=None, **kwargs):
    from analytics.metrics import worker_process_exited

    worker_process_exited(pid or os.getpid())
