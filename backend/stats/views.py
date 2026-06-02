import json

from django.db.models import Count
from django.http import HttpResponse, JsonResponse

from stats.builder import StatsBuilder


def stats_view(request):
    html = StatsBuilder().render()
    return HttpResponse(html, content_type="text/html")


def workers_view(request):
    from analytics.models import ExtractTask, Request
    from geoquery.celery import app

    # --- DB queue depths ---
    extract_counts = dict(
        ExtractTask.objects.values("status").annotate(n=Count("id")).values_list("status", "n")
    )
    request_counts = dict(
        Request.objects.values("status").annotate(n=Count("id")).values_list("status", "n")
    )

    # --- Celery worker inspection ---
    workers = []
    try:
        inspector = app.control.inspect(timeout=2.0)
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        stats = inspector.stats() or {}

        for name in set(active) | set(stats):
            running = active.get(name, [])
            queued = reserved.get(name, [])
            worker_stats = stats.get(name, {})
            workers.append({
                "name": name,
                "status": "online",
                "running": len(running),
                "reserved": len(queued),
                "running_tasks": [t.get("name", "unknown").split(".")[-1] for t in running],
                "total_processed": worker_stats.get("total", {}).get("analytics.tasks.processing.run_extract_task", 0),
            })
    except Exception:
        pass

    return JsonResponse({
        "workers": workers,
        "queues": {
            "extract_pending": extract_counts.get(0, 0),
            "extract_processing": extract_counts.get(2, 0),
            "requests_queued": request_counts.get(-1, 0),
            "requests_processing": request_counts.get(0, 0) + request_counts.get(2, 0),
        },
    })
