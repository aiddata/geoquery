from datasets.models import Dataset, DatasetResource
from features.models import FeatureCollection


def dataset_queryset():
    return Dataset.objects.filter(active=True, public=True).order_by("name")


def feature_collection_queryset():
    return FeatureCollection.objects.filter(active=True, public=True).order_by("name")


def get_collection_source(name):
    """The active+public Dataset or FeatureCollection backing a collection id.

    Checks Dataset first: `name` is independently unique within each
    table, but nothing enforces uniqueness across the two, so a
    hypothetical collision needs a deterministic winner rather than an
    arbitrary one. Dataset wins.
    """
    dataset = dataset_queryset().filter(name=name).first()
    if dataset is not None:
        return dataset
    return feature_collection_queryset().filter(name=name).first()


def all_collection_sources():
    """Every active+public Dataset and FeatureCollection, combined and name-ordered."""
    return sorted(
        list(dataset_queryset()) + list(feature_collection_queryset()),
        key=lambda source: source.name,
    )


def is_feature_collection(source):
    """Whether a collection/item source or item is a FeatureCollection rather than a Dataset/DatasetResource.

    Centralized here so other modules (e.g. serializers.py) can reuse
    the same type discrimination instead of re-deriving their own
    isinstance check against FeatureCollection.
    """
    return isinstance(source, FeatureCollection)


def get_items_for_collection(source):
    """DatasetResources under a Dataset; a single synthetic item for a FeatureCollection.

    A boundary set has no DatasetResource-equivalent sub-unit — it's
    distributed as one file, not a time series — so it maps to exactly
    one Item rather than one per underlying Feature row (which carry no
    metadata beyond geometry, and can number in the tens of thousands).
    """
    if is_feature_collection(source):
        return [source]
    return list(DatasetResource.objects.filter(dataset=source).select_related("dataset").order_by("name"))


def item_stac_id(item):
    if is_feature_collection(item):
        return f"{item.name}-item"
    return item.name


def get_item(source, item_id):
    for item in get_items_for_collection(source):
        if item_stac_id(item) == item_id:
            return item
    return None
