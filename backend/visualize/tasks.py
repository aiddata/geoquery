from celery import shared_task
from django.conf import settings

from .export import GistExporter


@shared_task
def sweep_export_gists():
    """Delete Colab export gists older than the configured TTL.

    Runs on a schedule because Colab fetches the gist server-side after the
    redirect, so there's no point at which we can safely delete it inline.
    """
    if not getattr(settings, "GITHUB_GIST_TOKEN", ""):
        return {"skipped": "GITHUB_GIST_TOKEN not configured"}
    max_age = getattr(settings, "EXPORT_GIST_TTL_SECONDS", 3600)
    return GistExporter.sweep_old_gists(max_age)
