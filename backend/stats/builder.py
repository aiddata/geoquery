from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from django.db.models import Count
from django.db.models.functions import TruncDay, TruncMonth, TruncYear

from analytics.models import ExtractTask, Request

# Map DB status codes → display groupings
_STATUS_GROUPS = {
    "completed":  [1],
    "pending":    [-1],
    "processing": [0, 2],
    "error":      [-2],
}


class StatsBuilder:
    """Collect the statistics payload the /stats page renders."""

    def __init__(self, output_path=None):
        self.output_path = Path(output_path) if output_path else None

    def collect(self) -> dict:
        """Return the report payload without writing to disk."""
        return self._collect()

    def build(self) -> str:
        """Collect and write the JSON payload to output_path.

        Written atomically: the stats view reads this file on every request, and
        a partially written file would be served as a parse error.
        """
        if not self.output_path:
            return "Error: no output_path specified"
        try:
            data = self._collect()
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
            tmp.replace(self.output_path)
            return "Success"
        except Exception as e:
            return f"Error: {e}"

    # ── private ───────────────────────────────────────────────────────────────

    def _collect(self) -> dict:
        # Per-status counts
        raw = {r["status"]: r["count"] for r in Request.objects.values("status").annotate(count=Count("id"))}
        status_counts = {
            label: sum(raw.get(code, 0) for code in codes)
            for label, codes in _STATUS_GROUPS.items()
        }
        total = sum(raw.values())

        # Time series for every combination of field × period
        time_series: dict[str, dict[str, list]] = {}
        trunc_fns = {"day": TruncDay, "month": TruncMonth, "year": TruncYear}
        fmt_str   = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}

        for field in ("submit_time", "complete_time"):
            time_series[field] = {}
            qs = Request.objects.filter(**{f"{field}__isnull": False})
            for period, trunc_fn in trunc_fns.items():
                rows = (
                    qs.annotate(bucket=trunc_fn(field))
                    .values("bucket")
                    .annotate(count=Count("id"))
                    .order_by("bucket")
                )
                time_series[field][period] = [
                    {"date": r["bucket"].strftime(fmt_str[period]), "count": r["count"]}
                    for r in rows
                    if r["bucket"] is not None
                ]

        # Extract task completions over time
        extract_time_series: dict[str, list] = {}
        qs_extract = ExtractTask.objects.filter(status=1, complete_time__isnull=False)
        for period, trunc_fn in trunc_fns.items():
            rows = (
                qs_extract.annotate(bucket=trunc_fn("complete_time"))
                .values("bucket")
                .annotate(count=Count("id"))
                .order_by("bucket")
            )
            extract_time_series[period] = [
                {"date": r["bucket"].strftime(fmt_str[period]), "count": r["count"]}
                for r in rows
                if r["bucket"] is not None
            ]

        # Extract task counts, in one GROUP BY over every status. This is the
        # expensive part of the report -- extract_tasks is ~280M rows across 56
        # partitions and no filter can prune it, so it reads millions of blocks.
        # It belongs here, in a task that runs every 5 minutes, rather than in a
        # view: it was previously served live to the page and took 16s a call,
        # which is what made the stats page 504 under any concurrency.
        extract_raw = {
            r["status"]: r["count"]
            for r in ExtractTask.objects.values("status").annotate(count=Count("id"))
        }
        extract_counts = {
            "completed": extract_raw.get(1, 0),
            "pending": extract_raw.get(0, 0),
            "claimed": extract_raw.get(3, 0),
            "processing": extract_raw.get(2, 0),
            "error": extract_raw.get(-1, 0),
            "total": sum(extract_raw.values()),
        }

        return {
            "total": total,
            "status_counts": status_counts,
            "extract_counts": extract_counts,
            "time_series": time_series,
            "extract_time_series": extract_time_series,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
