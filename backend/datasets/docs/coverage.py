"""Which datasets cover which boundary pages, from GeoQuery's own coverage data.

A global dataset covers every page in full: GeoQuery skips coverage for global
datasets, so they have no rows. Any other dataset covers a page where valid
coverage rows (analytics.coverage.valid_coverage) exist for the page's
features -- in full when every feature is covered, partially otherwise.

This trusts is_global. Datasets wrongly marked global will show as covering
everything until their flag is fixed (GEO-73).

Coverage still being computed (a dataset newly made non-global, or a dataset or
collection being reset, whose rows valid_coverage hides) shows as partial or
absent until it catches up; the next nightly build corrects it.
"""

from collections import defaultdict

from django.db.models import Count

FULL = "full"
PARTIAL = "partial"


def page_coverage(pages, datasets, using="replica") -> dict:
    """{page.slug: {dataset.id: FULL | PARTIAL}} for every page."""
    from analytics.coverage import valid_coverage
    from features.models import FeatMap

    fc_page = {fc.id: page.slug for page in pages for fc in page.collections}
    totals = defaultdict(int)
    counts = (
        FeatMap.objects.using(using).filter(fc_id__in=list(fc_page))
        .values("fc_id").annotate(n=Count("id")).values_list("fc_id", "n")
    )
    for fc_id, n in counts:
        totals[fc_page[fc_id]] += n

    result = {page.slug: {ds.id: FULL for ds in datasets if ds.is_global} for page in pages}
    regional = [ds.id for ds in datasets if not ds.is_global]
    if not regional:
        return result

    covered = defaultdict(int)
    # Coverage is unique on (geom, dataset) and feat_map on (fc, geom), so each
    # (dataset, fc, geom) joins to one row and a plain count is exact (and
    # avoids a sort-based aggregate at prod scale).
    rows = (
        valid_coverage(using)
        .filter(dataset_id__in=regional, geom__featmap__fc_id__in=list(fc_page))
        .values("dataset_id", "geom__featmap__fc_id")
        .annotate(n=Count("geom_id"))
    )
    for row in rows:
        covered[(fc_page[row["geom__featmap__fc_id"]], row["dataset_id"])] += row["n"]
    for (page_slug, dataset_id), n in covered.items():
        result[page_slug][dataset_id] = FULL if n >= totals[page_slug] else PARTIAL
    return result
