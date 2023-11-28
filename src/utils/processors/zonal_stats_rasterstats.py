# module for processor functions
import rasterstats as rs
from utils.helpers import get_dataset_resource_path_by_id, get_feat_by_id


def _rasterstats_default(feat, raster, stat):
    stats = rs.zonal_stats(feat, raster, stats=stat)
    output = stats[0][stat]
    return [(stat, output)]


def exists(self, name):
    return hasattr(self, name) and callable(getattr(self, name))


def rasterstats_default_min(feat, raster):
    output = _rasterstats_default(feat, raster, "min")
    return output


def rasterstats_default_max(feat, raster):
    output = _rasterstats_default(feat, raster, "max")
    return output


def rasterstats_default_mean(feat, raster):
    output = _rasterstats_default(feat, raster, "mean")
    return output


def rasterstats_default_sum(feat, raster):
    output = _rasterstats_default(feat, raster, "sum")
    return output


def rasterstats_default_count(feat, raster):
    output = _rasterstats_default(feat, raster, "count")
    return output


def rasterstats_default_categorical(feat, raster, **kwargs):
    mapping = kwargs["category_map"]
    stats = rs.zonal_stats(feat, raster, categorical=True, category_map=mapping)
    output = [(f"categorical_{k}", v) for k, v in stats[0].items()]

    for v, k in mapping.items():
        field = f"categorical_{k}"
        if field not in [i[0] for i in output]:
            output.append((field, 0))

    return output
