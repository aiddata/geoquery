# module for processor functions
import rasterstats as rs

from utils.helpers import get_feat_by_id, get_dataset_resource_path_by_id


def _rasterstats_default(feature_id, dataset_resource_id, stat):
    feat = get_feat_by_id(feature_id)
    raster = get_dataset_resource_path_by_id(dataset_resource_id)
    stats = rs.zonal_stats(feat, raster, stats=stat)
    output = stats[0][stat]
    return [(stat, output)]


def exists(self, name):
    return hasattr(self, name) and callable(getattr(self, name))

def rasterstats_default_min(feature_id, dataset_resource_id):
    output = _rasterstats_default(feature_id, dataset_resource_id, "min")
    return output

def rasterstats_default_max(feature_id, dataset_resource_id):
    output = _rasterstats_default(feature_id, dataset_resource_id, "max")
    return output

def rasterstats_default_max(feature_id, dataset_resource_id):
    output = _rasterstats_default(feature_id, dataset_resource_id, "mean")
    return output

def rasterstats_default_max(feature_id, dataset_resource_id):
    output = _rasterstats_default(feature_id, dataset_resource_id, "sum")
    return output

def rasterstats_default_max(feature_id, dataset_resource_id):
    output = _rasterstats_default(feature_id, dataset_resource_id, "count")
    return output

def rasterstats_default_categorical(feature_id, dataset_resource_id, mapping):
    feat = get_feat_by_id(feature_id)
    raster = get_dataset_resource_path_by_id(dataset_resource_id)
    stats = rs.zonal_stats(
        feat, raster, categorical=True, category_map=mapping
    )
    output = [(f"categorical_{k}", v) for k, v in stats.items()]
    return output
