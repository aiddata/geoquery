# module for processor functions
import rasterstats as rs


def _rasterstats_default(feat, raster, stat, **kwargs):
    kwargs["nodata"] = kwargs["nodata"] if "nodata" in kwargs else None
    stats = rs.zonal_stats(feat, raster, stats=stat, **kwargs)
    output = stats[0][stat]
    return [(kwargs["name"], output)]


def rasterstats_default_min(feat, raster, **kwargs):
    output = _rasterstats_default(feat, raster, "min", **kwargs)
    return output


def rasterstats_default_max(feat, raster, **kwargs):
    output = _rasterstats_default(feat, raster, "max", **kwargs)
    return output


def rasterstats_default_mean(feat, raster, **kwargs):
    output = _rasterstats_default(feat, raster, "mean", **kwargs)
    return output


def rasterstats_default_sum(feat, raster, **kwargs):
    output = _rasterstats_default(feat, raster, "sum", **kwargs)
    return output


def rasterstats_default_count(feat, raster, **kwargs):
    output = _rasterstats_default(feat, raster, "count", **kwargs)
    return output


def rasterstats_default_categorical(feat, raster, **kwargs):
    mapping = kwargs["category_map"]
    nodata = kwargs["nodata"] if "nodata" in kwargs else None
    stats = rs.zonal_stats(
        feat, raster, categorical=True, category_map=mapping, nodata=nodata
    )
    return _categorical_output(kwargs["name"], stats[0], mapping)


def _categorical_output(name, counts, mapping):
    """One feature's category counts as (column, count) pairs, with a zero for
    every mapped category the feature does not contain."""
    output = [(f"{name}_{k}", v) for k, v in counts.items()]

    for v, k in mapping.items():
        field = f"{name}_{k}"
        if field not in [i[0] for i in output]:
            output.append((field, 0))

    return output


# Batch forms, used by block extraction (analytics.blocks). rasterstats opens
# the raster once per call and computes every requested stat from a single
# windowed read per feature, so one call here replaces len(feats) x len(stats)
# calls to the single-feature functions above. Arguments match that path,
# and percentage-coverage calls isolate points to preserve per-feature state
# (see rasterstats_batch).

# Single-feature function -> the stat it computes, for the functions that can
# share one batched call.
BATCH_STATS = {
    "rasterstats_default_min": "min",
    "rasterstats_default_max": "max",
    "rasterstats_default_mean": "mean",
    "rasterstats_default_sum": "sum",
    "rasterstats_default_count": "count",
}


def rasterstats_batch(feats, raster, stats, **kwargs):
    """Every stat in ``stats`` for every geometry in ``feats``, one dict per
    feature, as _rasterstats_default computes them one at a time."""
    kwargs["nodata"] = kwargs["nodata"] if "nodata" in kwargs else None

    def run(features):
        # A fresh list per call: rasterstats appends count when mean needs
        # it to combine split geometries (the limit option).
        return rs.zonal_stats(features, raster, stats=list(stats), **kwargs)

    if not (kwargs.get("percent_cover_weighting")
            or kwargs.get("percent_cover_selection") is not None):
        return run(feats)

    # The installed rasterstats disables percentage coverage for points by
    # mutating flags shared by the rest of its feature loop. Isolate Point
    # and MultiPoint from other geometries so a preceding point cannot
    # silently remove polygon weighting/selection. Keep each group batched,
    # and restore input order so results still map to the correct features.
    feats = list(feats)
    groups = {False: [], True: []}
    for index, feat in enumerate(feats):
        groups[feat.geom_type in ("Point", "MultiPoint")].append(index)
    results = [None] * len(feats)
    for indices in groups.values():
        if indices:
            rows = run([feats[i] for i in indices])
            for index, row in zip(indices, rows, strict=True):
                results[index] = row
    return results


def rasterstats_batch_categorical(feats, raster, **kwargs):
    """rasterstats_default_categorical for every geometry in ``feats``, one
    list of (column, count) pairs per feature."""
    mapping = kwargs["category_map"]
    nodata = kwargs["nodata"] if "nodata" in kwargs else None
    stats = rs.zonal_stats(
        feats, raster, categorical=True, category_map=mapping, nodata=nodata
    )
    return [_categorical_output(kwargs["name"], counts, mapping) for counts in stats]
