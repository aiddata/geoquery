# module for processor functions
import rasterio
import rasterstats as rs


def _rasterstats_kwargs(kwargs):
    default_kwargs = {
        "all_touched": True,
        "nodata": None,
    }
    # create actual kwargs by merging default_kwargs with kwargs
    for k, v in default_kwargs.items():
        if k not in kwargs:
            kwargs[k] = v
    return kwargs


def _rasterstats_default(feat, raster, stat, **kwargs):
    kwargs = _rasterstats_kwargs(kwargs)
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


def _categorical_output(stats, kwargs):
    mapping = kwargs["category_map"]
    output = [(f"{kwargs['name']}_{k}", v) for k, v in stats.items()]

    for v, k in mapping.items():
        field = f"{kwargs['name']}_{k}"
        if field not in [i[0] for i in output]:
            output.append((field, 0))

    return output


def rasterstats_default_categorical(feat, raster, **kwargs):
    mapping = kwargs["category_map"]
    nodata = kwargs["nodata"] if "nodata" in kwargs else None
    stats = rs.zonal_stats(
        feat, raster, categorical=True, category_map=mapping, nodata=nodata
    )
    return _categorical_output(stats[0], kwargs)


# --- precise forms -----------------------------------------------------------
#
# Area-aware statistics from the AidData rasterstats fork. Each pixel is
# weighted by the fraction of it the feature covers (percent cover), and mean
# also weights each pixel row by its true area at that latitude, which assumes
# an EPSG:4326 raster. Percent cover rasterizes every window at scale x scale
# sub-pixels, so `limit` splits large features into tiles of at most that many
# source pixels (~200 MB peak per tile at these defaults). Processing option
# and task kwargs override any default here. Point features get no percent
# cover (the fork disables it), and precise count is a float.

_PRECISE_DEFAULTS = {
    "percent_cover_weighting": True,
    "percent_cover_scale": 10,
    "limit": 1_000_000,
}
_PRECISE_STAT_DEFAULTS = {"mean": {"latitude_correction": True}}
_PRECISE_CONVERT = {"count": float}


def _precise_kwargs(stat, kwargs):
    return {**_PRECISE_DEFAULTS, **_PRECISE_STAT_DEFAULTS.get(stat, {}), **kwargs}


def rasterstats_precise_mean(feat, raster, **kwargs):
    return _rasterstats_default(feat, raster, "mean", **_precise_kwargs("mean", kwargs))


def rasterstats_precise_sum(feat, raster, **kwargs):
    return _rasterstats_default(feat, raster, "sum", **_precise_kwargs("sum", kwargs))


def rasterstats_precise_count(feat, raster, **kwargs):
    # the fork returns int 0 for empty windows and int 1 for points
    [(name, value)] = _rasterstats_default(
        feat, raster, "count", **_precise_kwargs("count", kwargs)
    )
    return [(name, float(value))]


# --- batch forms -------------------------------------------------------------
#
# The same computations over many features with the raster opened once:
# gen_zonal_stats opens its Raster once and reads a window per feature, so a
# lease page pays the open (and GDAL's header and overview setup) once per
# resource per geometry block instead of once per feature. Each feature's
# statistics come from its own window exactly as in the single-feature call,
# so the values are identical (see test_batch_processors).
#
# A batch function is ``batch(feats, raster, **kwargs)`` and yields
# ``(index, result)`` in order, one per feature, where result is the
# single-feature function's return value or the exception that feature
# raised. Consumers may stop between features (generator close releases the
# raster).
#
# A feature that raises kills gen_zonal_stats' generator, so the batch
# restarts it after the failed feature. A failure before the first feature of
# a (re)started generator is either that feature or the raster itself; the
# raster is tried on its own to tell which. Two consecutive open failures fail
# the rest of the block with that error rather than reopening per feature.


def _opens(raster):
    try:
        with rasterio.open(raster):
            return True
    except Exception:
        return False


def _batched(feats, raster, start_generator, to_result):
    n = len(feats)
    start = 0
    open_failures = 0
    while start < n:
        produced = 0
        generator = start_generator(feats[start:])
        try:
            for stats in generator:
                yield start + produced, to_result(stats)
                produced += 1
                open_failures = 0
            return
        except Exception as exc:
            failed = start + produced
            if produced == 0 and not _opens(raster):
                open_failures += 1
                if open_failures >= 2:
                    for i in range(failed, n):
                        yield i, exc
                    return
                continue
            open_failures = 0
            yield failed, exc
            start = failed + 1
        finally:
            generator.close()


def _batch_default(stat, convert=None):
    def batch(feats, raster, **kwargs):
        kwargs = _rasterstats_kwargs(kwargs)
        return _batched(
            feats,
            raster,
            lambda rest: rs.gen_zonal_stats(rest, raster, stats=stat, **kwargs),
            lambda stats: [
                (kwargs["name"], stats[stat] if convert is None else convert(stats[stat]))
            ],
        )

    batch.__name__ = f"rasterstats_default_{stat}_batch"
    return batch


def rasterstats_default_categorical_batch(feats, raster, **kwargs):
    mapping = kwargs["category_map"]
    nodata = kwargs["nodata"] if "nodata" in kwargs else None
    return _batched(
        feats,
        raster,
        lambda rest: rs.gen_zonal_stats(
            rest, raster, categorical=True, category_map=mapping, nodata=nodata
        ),
        lambda stats: _categorical_output(stats, kwargs),
    )


def _batch_precise(stat):
    default = _batch_default(stat, _PRECISE_CONVERT.get(stat))

    def batch(feats, raster, **kwargs):
        return default(feats, raster, **_precise_kwargs(stat, kwargs))

    batch.__name__ = f"rasterstats_precise_{stat}_batch"
    return batch


BATCH = {
    "rasterstats_default_min": _batch_default("min"),
    "rasterstats_default_max": _batch_default("max"),
    "rasterstats_default_mean": _batch_default("mean"),
    "rasterstats_default_sum": _batch_default("sum"),
    "rasterstats_default_count": _batch_default("count"),
    "rasterstats_default_categorical": rasterstats_default_categorical_batch,
    "rasterstats_precise_mean": _batch_precise("mean"),
    "rasterstats_precise_sum": _batch_precise("sum"),
    "rasterstats_precise_count": _batch_precise("count"),
}
