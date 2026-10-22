"""Processor functions for extract tasks.

Each processor is called as ``func(feat, dataset_path, name=..., **kwargs)`` and
returns a list of ``(column_name, value)`` tuples. See
``analytics.tasks.processing._extract`` for the call site.

BATCH_REGISTRY holds batch forms for processors that can reuse one open
resource across many features: ``batch(feats, dataset_path, name=..., **kwargs)``
yields ``(index, result_or_exception)`` per feature, in order, with the same
values the single-feature function would return. Lease pages use them (see
``analytics.tasks.leases``); a processor without one is called per feature.
The vector processors open a GeoPackage and filter per feature, so they keep
the per-feature call.

REGISTRY keys are persisted in ``analytics.models.ProcessingOption.function`` and in
the dataset ingest JSON published in aiddata/geo-datasets. Renaming a key is a data
migration, not a refactor.
"""

from analytics.processors.acled_filter_agg import acled_dynamic_filter_and_agg
from analytics.processors.cports_filter_agg import cports_v20_dynamic_filter_and_agg
from analytics.processors.gcdf_filter_agg import gcdf_v301_dynamic_filter_and_agg
from analytics.processors.landmarkmap_filter_agg import landmarkmap_filter_and_agg
from analytics.processors.ucdp_filter_agg import ged261_dynamic_filter_and_agg
from analytics.processors.zonal_stats_rasterstats import (
    BATCH,
    rasterstats_default_categorical,
    rasterstats_default_count,
    rasterstats_default_max,
    rasterstats_default_mean,
    rasterstats_default_min,
    rasterstats_default_sum,
)

REGISTRY = {
    f.__name__: f
    for f in (
        rasterstats_default_min,
        rasterstats_default_max,
        rasterstats_default_mean,
        rasterstats_default_sum,
        rasterstats_default_count,
        rasterstats_default_categorical,
        gcdf_v301_dynamic_filter_and_agg,
        cports_v20_dynamic_filter_and_agg,
        ged261_dynamic_filter_and_agg,
        acled_dynamic_filter_and_agg,
        landmarkmap_filter_and_agg,
    )
}

BATCH_REGISTRY = dict(BATCH)

__all__ = ["BATCH_REGISTRY", "REGISTRY", *REGISTRY]
