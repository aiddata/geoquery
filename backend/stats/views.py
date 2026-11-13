"""Stats data endpoint.

The stats page lives in the SvelteKit app at ``/stats``. This endpoint gives it
the payload, read from a snapshot that
``analytics.tasks.maintenance.build_stats_report`` regenerates hourly by default
at ``settings.STATS_REPORT_PATH``. Setting ``STATS_REPORT_INTERVAL_SECONDS=0``
disables the rebuild. The endpoint then keeps serving the last snapshot.

Normal requests use only the snapshot. The page used to poll a live endpoint for
queue counts, which ran a GROUP BY over ~280M ``extract_tasks`` rows -- a global
aggregate no filter can prune -- at ~16s and millions of block reads per call.
That made the page 504 as soon as two requests overlapped. The counts are part
of the snapshot instead, so normal requests are file reads.
"""
import json
import time
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Min
from django.http import JsonResponse
from django.utils import timezone

from analytics.models import Request
from stats.builder import StatsBuilder

# Requests that have been submitted but not finished: queued (-1) and in
# progress (0, 2). See stats.builder._STATUS_GROUPS.
_UNFINISHED = (-1, 0, 2)


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
    cold-start convenience, not a normal code path. With the report disabled
    there is no live build at all: it would run that aggregate on every page
    load, which is worse than the schedule that was turned off.
    """
    path = _report_path()
    if path.exists():
        try:
            return JsonResponse(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            pass  # corrupt or unreadable snapshot: fall through to a live build
    if not settings.STATS_REPORT_ENABLED:
        return JsonResponse(
            {"error": "Statistics reporting is disabled."}, status=503
        )
    return JsonResponse(StatsBuilder().collect())


def status_data(request):
    """Live service status for the top of the /stats page.

    Unlike the snapshot this is computed per request, so it has to stay cheap:
    one aggregate over the small requests table (on the standby) and a file
    stat. "offline" is not a state here: the page shows it when it can't reach
    this endpoint at all.

    - backlogged: the oldest unfinished request has waited longer than
      STATUS_BACKLOG_MINUTES.
    - delayed: the hourly snapshot is more than three intervals old, so the
      scheduled background jobs appear to have stalled.
    - healthy: otherwise.
    """
    now = timezone.now()
    queue = (
        Request.objects.using("replica")
        .filter(status__in=_UNFINISHED)
        .aggregate(count=Count("id"), oldest=Min("submit_time"))
    )
    oldest_wait = (now - queue["oldest"]).total_seconds() if queue["oldest"] else 0
    backlog_after = settings.STATUS_BACKLOG_MINUTES * 60

    path = _report_path()
    snapshot_age = time.time() - path.stat().st_mtime if path.exists() else None
    stale = (
        settings.STATS_REPORT_ENABLED
        and snapshot_age is not None
        and snapshot_age > 3 * settings.STATS_REPORT_INTERVAL_SECONDS
    )

    if oldest_wait > backlog_after:
        state = "backlogged"
    elif stale:
        state = "delayed"
    else:
        state = "healthy"
    return JsonResponse(
        {
            "state": state,
            "unfinished_requests": queue["count"],
            "oldest_wait_seconds": round(oldest_wait),
            "backlog_after_seconds": backlog_after,
            "snapshot_age_seconds": None if snapshot_age is None else round(snapshot_age),
            "checked_at": now.isoformat(),
        }
    )
