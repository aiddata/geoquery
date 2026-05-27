from django.http import HttpResponse

from stats.builder import StatsBuilder


def stats_view(request):
    html = StatsBuilder().render()
    return HttpResponse(html, content_type="text/html")
