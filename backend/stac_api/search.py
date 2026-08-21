import datetime

from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from .serializers import item_geometry_and_datetime
from .sources import all_collection_sources, get_items_for_collection
from .utils import bbox_from_geometry


def parse_bbox_param(raw):
    if not raw:
        return None
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = list(raw)
    if len(parts) != 4:
        raise ValidationError({"bbox": "must be 4 comma-separated numbers, or a 4-element array"})
    try:
        return [float(p) for p in parts]
    except (TypeError, ValueError):
        raise ValidationError({"bbox": "must be 4 comma-separated numbers, or a 4-element array"})


def _parse_single_datetime(raw):
    parsed = parse_datetime(raw)
    if parsed is None:
        raise ValidationError({"datetime": f"invalid RFC3339 datetime: {raw!r}"})
    if django_timezone.is_naive(parsed):
        parsed = django_timezone.make_aware(parsed, datetime.timezone.utc)
    return parsed


def parse_datetime_param(raw):
    """Returns (start, end); either side is None for an open interval."""
    if not raw:
        return None, None
    if "/" in raw:
        start_raw, end_raw = raw.split("/", 1)
    else:
        start_raw = end_raw = raw
    start = None if start_raw in ("", "..") else _parse_single_datetime(start_raw)
    end = None if end_raw in ("", "..") else _parse_single_datetime(end_raw)
    return start, end


def parse_limit_param(raw, default=100):
    if raw is None:
        return default
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({"limit": "must be an integer"})
    if limit < 1 or limit > 1000:
        raise ValidationError({"limit": "must be between 1 and 1000"})
    return limit


def parse_collections_param(raw):
    """Note: for GET, use comma-separated values (?collections=a,b) — a repeated
    query key (?collections=a&collections=b) silently keeps only the last
    value, since QueryDict.get() does not return the full multi-value list."""
    if not raw:
        return None
    if isinstance(raw, str):
        return set(raw.split(","))
    return set(raw)


def _bbox_overlaps(item_bbox, query_bbox):
    if item_bbox is None:
        return False
    ixmin, iymin, ixmax, iymax = item_bbox
    qxmin, qymin, qxmax, qymax = query_bbox
    return not (ixmax < qxmin or ixmin > qxmax or iymax < qymin or iymin > qymax)


def _datetime_in_range(dt, start, end):
    if dt is None:
        return False
    if start is not None and dt < start:
        return False
    if end is not None and dt > end:
        return False
    return True


def search_items(bbox=None, datetime_range=(None, None), collection_names=None, limit=100):
    """Returns (matched_items, total_matched_count).

    Filters at the Python level across every active+public source's items.
    Fine at GeoQuery's current data volume (single digits of datasets,
    each with well under a thousand resources); if that grows enough to
    matter, push bbox/datetime filtering into SQL against
    DatasetResource.spatial_extent/temporal instead of fetching everything.
    """
    start, end = datetime_range
    sources = all_collection_sources()
    if collection_names is not None:
        sources = [s for s in sources if s.name in collection_names]

    matched = []
    for source in sources:
        for item in get_items_for_collection(source):
            geom, dt = item_geometry_and_datetime(item)
            if bbox is not None and not _bbox_overlaps(bbox_from_geometry(geom), bbox):
                continue
            if (start is not None or end is not None) and not _datetime_in_range(dt, start, end):
                continue
            matched.append(item)

    return matched[:limit], len(matched)
