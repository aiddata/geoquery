import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoquery.settings")

app = Celery("geoquery")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Register the parent-process exporter before Celery starts its worker pool.
import analytics.background_metrics  # noqa: E402,F401
