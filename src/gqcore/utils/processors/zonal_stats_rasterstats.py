# module for processor functions
import rasterstats as rs



def _rasterstats_default(feat, raster, stat, **kwargs):
    nodata = kwargs["nodata"] if "nodata" in kwargs else None
    stats = rs.zonal_stats(
        feat, raster,
        stats=stat,
        nodata=nodata,
        **kwargs
    )
    output = stats[0][stat]
    return [(stat, output)]


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
    stats = rs.zonal_stats(feat, raster, categorical=True, category_map=mapping, nodata=nodata)
    output = [(f"categorical_{k}", v) for k, v in stats[0].items()]

    for v, k in mapping.items():
        field = f"categorical_{k}"
        if field not in [i[0] for i in output]:
            output.append((field, 0))

    return output
