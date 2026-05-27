from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from django.db.models import Count
from django.db.models.functions import TruncDay, TruncMonth, TruncYear

from analytics.models import Request

# Map DB status codes → display groupings
_STATUS_GROUPS = {
    "completed":  [1],
    "pending":    [-1],
    "processing": [0, 2],
    "error":      [-2],
}


class StatsBuilder:
    """Generate a self-contained HTML statistics report for GeoQuery requests."""

    def __init__(self, output_path=None):
        self.output_path = Path(output_path) if output_path else None

    def render(self) -> str:
        """Return the rendered HTML string without writing to disk."""
        return self._render(self._collect())

    def build(self) -> str:
        """Render and write the HTML file to output_path."""
        if not self.output_path:
            return "Error: no output_path specified"
        try:
            data = self._collect()
            html = self._render(data)
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, "w", encoding="utf-8") as f:
                f.write(html)
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

        return {
            "total": total,
            "status_counts": status_counts,
            "time_series": time_series,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }

    @staticmethod
    def _render(data: dict) -> str:
        from .template import TEMPLATE
        return TEMPLATE.replace("__GQ_STATS__", json.dumps(data, default=str))
