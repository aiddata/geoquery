import json

from django.db.models import Count
from django.http import HttpResponse, JsonResponse

from stats.builder import StatsBuilder


def stats_view(request):
    html = StatsBuilder().render()
    return HttpResponse(html, content_type="text/html")


def workers_view(request):
    # Status codes: 0=pending, 3=claimed, 2=processing, 1=completed, -1=error
    from analytics.models import ExtractTask, Request

    extract_counts = dict(
        ExtractTask.objects.values("status").annotate(n=Count("id")).values_list("status", "n")
    )
    request_counts = dict(
        Request.objects.values("status").annotate(n=Count("id")).values_list("status", "n")
    )

    return JsonResponse({
        "queues": {
            "extract_pending": extract_counts.get(0, 0),
            "extract_claimed": extract_counts.get(3, 0),
            "extract_processing": extract_counts.get(2, 0),
            "extract_completed": extract_counts.get(1, 0),
            "extract_error": extract_counts.get(-1, 0),
            "requests_queued": request_counts.get(-1, 0),
            "requests_processing": request_counts.get(0, 0) + request_counts.get(2, 0),
        },
    })
