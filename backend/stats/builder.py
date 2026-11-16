from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from django.db.models import Count
from django.db.models.functions import Lower, Trim, TruncDay, TruncMonth, TruncYear

from analytics.models import ExtractTask, LegacyRequest, Request
from datasets.models import Dataset
from features.models import FeatMap, FeatureCollection

# How many datasets and boundary sets the "most requested" lists show.
TOP_N = 10
# Turnaround is reported over requests completed in this many recent days.
TURNAROUND_DAYS = 30

# Map DB status codes → display groupings
_STATUS_GROUPS = {
    "completed":  [1],
    "pending":    [-1],
    "processing": [0, 2],
    "error":      [-2],
}

# The report reads every extract_tasks partition once per build. The former
# four scans every five minutes cost ~3 cores and a rw pooler slot on the
# primary; none of this needs read-after-write consistency, so it runs on a
# standby. Only the backend and background-worker pods are given PG_RO_*;
# anywhere else the alias falls back to the primary (see settings._pg).
_DB = "replica"


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
        raw = {r["status"]: r["count"] for r in Request.objects.using(_DB).values("status").annotate(count=Count("id"))}
        status_counts = {
            label: sum(raw.get(code, 0) for code in codes)
            for label, codes in _STATUS_GROUPS.items()
        }
        total = sum(raw.values())

        # Time series for every combination of field × period, for the
        # current system and, separately, for requests imported from earlier
        # versions (the page can show or hide those).
        fmt_str = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
        time_series = _request_series(Request)
        legacy_time_series = _request_series(LegacyRequest)

        # When the current system took over: the day of its first request.
        first = Request.objects.using(_DB).order_by("submit_time").values_list("submit_time", flat=True).first()
        cutover = first.strftime("%Y-%m-%d") if first else None

        # One grouped scan per dataset supplies both counts and completions.
        # Explicit dataset filters prune partitions and bound each query's
        # lifetime on the standby. Include inactive/private datasets too.
        extract_raw = Counter()
        completed_days = Counter()
        for dataset_id in Dataset.objects.using(_DB).values_list("id", flat=True):
            rows = (
                ExtractTask.objects.using(_DB)
                .filter(dataset_id=dataset_id)
                .annotate(bucket=TruncDay("complete_time"))
                .values("status", "bucket")
                .annotate(count=Count("id"))
                .order_by()
            )
            for row in rows:
                extract_raw[row["status"]] += row["count"]
                # Null dates still contribute to counts, and retries/errors
                # with old completion dates must not enter the series.
                if row["status"] == 1 and row["bucket"] is not None:
                    completed_days[row["bucket"]] += row["count"]

        extract_time_series: dict[str, list] = {}
        for period, fmt in fmt_str.items():
            buckets = Counter()
            for day, count in completed_days.items():
                buckets[day.strftime(fmt)] += count
            extract_time_series[period] = [
                {"date": date, "count": count}
                for date, count in sorted(buckets.items())
            ]
        extract_counts = {
            "completed": extract_raw.get(1, 0),
            "pending": extract_raw.get(0, 0),
            "claimed": extract_raw.get(3, 0),
            "processing": extract_raw.get(2, 0),
            "error": extract_raw.get(-1, 0),
            "total": sum(extract_raw.values()),
        }

        # Requests imported from the previous version of GeoQuery. Reported as
        # its own figure rather than folded into the counts above: those
        # describe the current system's throughput, and a decade of another
        # system's history would distort every chart built from them.
        legacy_request_count = LegacyRequest.objects.using(_DB).count()

        return {
            "total": total,
            "datasets_available": Dataset.objects.using(_DB).filter(active=True, public=True).count(),
            "boundary_sets_available": _public_collections().count(),
            # Features (areas) across those sets; a feature in two sets counts twice.
            "boundary_features_available": FeatMap.objects.using(_DB)
            .filter(fc__in=_public_collections())
            .count(),
            "turnaround": self._turnaround(),
            **self._people(),
            **self._most_requested(),
            "status_counts": status_counts,
            "extract_counts": extract_counts,
            "time_series": time_series,
            "extract_time_series": extract_time_series,
            "legacy_request_count": legacy_request_count,
            "legacy_time_series": legacy_time_series,
            "cutover": cutover,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }

    def _people(self) -> dict:
        """Distinct requesters, and the organizations they come from.

        Counted across current requests and those imported from earlier
        versions of GeoQuery. People are counted by email address, and
        organizations by email domain, so a personal provider such as
        gmail.com counts as one organization.
        """
        def emails(model) -> set[str]:
            rows = (
                model.objects.using(_DB)
                .exclude(contact__isnull=True)
                .annotate(email=Lower(Trim("contact")))
                .values_list("email", flat=True)
                .distinct()
            )
            return {e for e in rows if e and "@" in e}

        everyone = emails(Request) | emails(LegacyRequest)
        domains = {a.rsplit("@", 1)[1] for a in everyone} - {""}
        return {"users": len(everyone), "organizations": len(domains)}

    def _turnaround(self) -> dict:
        """Median and 90th-percentile submit-to-complete time, recent requests only."""
        since = datetime.now(timezone.utc) - timedelta(days=TURNAROUND_DAYS)
        rows = (
            Request.objects.using(_DB)
            .filter(status=1, complete_time__gte=since, submit_time__isnull=False)
            .values_list("submit_time", "complete_time")
        )
        seconds = sorted((done - submitted).total_seconds() for submitted, done in rows if done >= submitted)
        result = {"days": TURNAROUND_DAYS, "count": len(seconds), "median_seconds": None, "p90_seconds": None}
        if seconds:
            result["median_seconds"] = median(seconds)
            result["p90_seconds"] = seconds[math.ceil(0.9 * len(seconds)) - 1]
        return result

    def _most_requested(self) -> dict:
        """The datasets and boundary sets in the most requests.

        Counted from each request's own record: the datasets it named, and the
        collections its features belong to. Only public, active datasets and
        collections are listed, so the page never names private ones, and
        uploaded custom boundaries are left out. Legacy requests use another
        format and are not counted.
        """
        dataset_counts = Counter()
        collection_counts = Counter()
        for data in Request.objects.using(_DB).values_list("data", flat=True).iterator():
            data = data or {}
            dataset_counts.update(
                {d["dataset_name"] for d in data.get("datasets") or [] if d.get("dataset_name")}
            )
            feature_ids = data.get("feature_ids") or []
            if feature_ids:
                collection_counts.update(
                    FeatMap.objects.using(_DB)
                    .filter(geom_id__in=feature_ids)
                    .values_list("fc_id", flat=True)
                    .distinct()
                )

        titles = dict(
            Dataset.objects.using(_DB)
            .filter(active=True, public=True, name__in=dataset_counts)
            .values_list("name", "title")
        )
        top_datasets = [
            {"name": name, "title": titles[name] or name, "requests": n}
            for name, n in dataset_counts.most_common()
            if name in titles
        ][:TOP_N]

        fc_titles = {
            fc_id: title or name
            for fc_id, title, name in _public_collections()
            .filter(id__in=collection_counts)
            .values_list("id", "title", "name")
        }
        top_boundary_sets = [
            {"id": fc_id, "title": fc_titles[fc_id], "requests": n}
            for fc_id, n in collection_counts.most_common()
            if fc_id in fc_titles
        ][:TOP_N]
        return {"top_datasets": top_datasets, "top_boundary_sets": top_boundary_sets}


_TRUNC = {"day": (TruncDay, "%Y-%m-%d"), "month": (TruncMonth, "%Y-%m"), "year": (TruncYear, "%Y")}


def _request_series(model) -> dict[str, dict[str, list]]:
    """Request counts by submit and completion date, per day, month and year."""
    series: dict[str, dict[str, list]] = {}
    for field in ("submit_time", "complete_time"):
        series[field] = {}
        qs = model.objects.using(_DB).filter(**{f"{field}__isnull": False})
        for period, (trunc_fn, fmt) in _TRUNC.items():
            rows = (
                qs.annotate(bucket=trunc_fn(field))
                .values("bucket")
                .annotate(count=Count("id"))
                .order_by("bucket")
            )
            series[field][period] = [
                {"date": r["bucket"].strftime(fmt), "count": r["count"]}
                for r in rows
                if r["bucket"] is not None
            ]
    return series


def _public_collections():
    return FeatureCollection.objects.using(_DB).filter(active=True, public=True, is_user_upload=False)
