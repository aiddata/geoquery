"""Stats data endpoint.

The stats page lives in the SvelteKit app at ``/stats``. This endpoint gives it
the payload, read from a snapshot that
``analytics.tasks.maintenance.build_stats_report`` regenerates every 5 minutes
at ``settings.STATS_REPORT_PATH``.

Nothing here queries the database. The page used to poll a live endpoint for
queue counts, which ran a GROUP BY over ~280M ``extract_tasks`` rows -- a global
aggregate no filter can prune -- at ~16s and millions of block reads per call.
That made the page 504 as soon as two requests overlapped. The counts are part
of the 5-minute snapshot instead, so every request is a file read.
"""
import json
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse

from stats.builder import StatsBuilder


def _report_path():
    return Path(
        getattr(
            settings,
            "STATS_REPORT_PATH",
            str(settings.REQUESTS_DIR / "geoquery_stats.json"),
        )
    )


def stats_data(request):
    """Return the most recent statistics snapshot.

    Falls back to collecting live only when the snapshot does not exist yet
    (first boot, before the beat task has run). That path is slow by nature --
    it is the same aggregate the snapshot exists to avoid -- so it is a
    cold-start convenience, not a normal code path.
    """
    path = _report_path()
    if path.exists():
        try:
            return JsonResponse(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            pass  # corrupt or unreadable snapshot: fall through to a live build
    return JsonResponse(StatsBuilder().collect())
