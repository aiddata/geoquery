import datetime
import json

from django.utils import timezone as django_timezone

STAC_VERSION = "1.0.0"


def build_url(request, path):
    return request.build_absolute_uri(path)


def bbox_from_geometry(geom):
    if geom is None:
        return None
    xmin, ymin, xmax, ymax = geom.extent
    return [xmin, ymin, xmax, ymax]


def geojson_from_geometry(geom):
    if geom is None:
        return None
    return json.loads(geom.geojson)


def to_rfc3339(dt):
    """Formats a datetime as RFC3339 UTC ('...Z'), STAC's required datetime shape.

    Naive datetimes are treated as already-UTC rather than raising or
    silently assuming the server's local timezone.
    """
    if dt is None:
        return None
    if django_timezone.is_naive(dt):
        dt = django_timezone.make_aware(dt, datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
