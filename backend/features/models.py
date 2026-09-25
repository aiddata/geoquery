from django.contrib.gis.db import models
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GistIndex
from django.db.models.signals import pre_delete
from django.dispatch import receiver


class FeatureCollection(models.Model):
    """Feature collections table for managing geospatial feature datasets."""

    id = models.AutoField(primary_key=True)
    active = models.BooleanField(default=False)
    public = models.BooleanField(default=False)
    name = models.CharField(max_length=200, unique=True)
    path = models.CharField(max_length=200, unique=True)
    file_extension = models.CharField(max_length=10, blank=True, null=True)
    file_mask = models.CharField(max_length=100, blank=True, null=True)
    title = models.CharField(max_length=200, blank=True, null=True)
    short_name = models.CharField(max_length=100, blank=True, null=True)
    description = models.CharField(max_length=1000, blank=True, null=True)
    details = models.CharField(max_length=1000, blank=True, null=True)
    tags = ArrayField(models.CharField(max_length=100), blank=True, null=True)
    citation = models.CharField(max_length=500, blank=True, null=True)
    source_name = models.CharField(max_length=100, blank=True, null=True)
    source_url = models.CharField(max_length=200, blank=True, null=True)
    # Same contract as Dataset.license/license_url -- see datasets.models.
    license = models.CharField(max_length=100, blank=True, null=True)
    license_url = models.URLField(blank=True, null=True)
    other = models.JSONField(blank=True, null=True)
    temporal_start = models.DateTimeField(blank=True, null=True)
    temporal_end = models.DateTimeField(blank=True, null=True)
    temporal_name = models.CharField(max_length=100, blank=True, null=True)
    temporal_type = models.CharField(max_length=100, blank=True, null=True)
    is_global = models.BooleanField(default=False)
    spatial_extent = models.GeometryField(blank=True, null=True)
    date_added = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    ingest_src = models.CharField(max_length=200, blank=True, null=True)
    group_name = models.CharField(max_length=100, blank=True, null=True)
    group_title = models.CharField(max_length=100, blank=True, null=True)
    group_class = models.CharField(max_length=100, blank=True, null=True)
    group_level = models.IntegerField(blank=True, null=True)
    is_user_upload = models.BooleanField(default=False)
    upload_metadata = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = "feature_collections"

    def __str__(self):
        return self.name

    @classmethod
    def search_active_public(cls, query=""):
        """Active, public feature collections optionally filtered by a name/title/description search.

        Shared by the internal autocomplete endpoint
        (features.views.FeatureCollectionAutocompleteView) and the public
        boundaries/autocomplete/ endpoint (public_api.views), so the
        active+public+search filter rule lives in exactly one place.
        """
        queryset = cls.objects.filter(active=True, public=True)
        if query:
            queryset = queryset.filter(
                models.Q(name__icontains=query)
                | models.Q(title__icontains=query)
                | models.Q(description__icontains=query)
            )
        return queryset.order_by("name")


class FeatureQuerySet(models.QuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        # bulk_create skips Feature.save(), so apply the same rule here so the
        # returned instances carry the point the database stored.
        objs = list(objs)
        for obj in objs:
            obj.sync_representative_point()
        created = super().bulk_create(objs, *args, **kwargs)
        for obj in created:
            obj._snapshot_geometry()
        return created


def _as_geometry(value):
    if isinstance(value, str):
        return GEOSGeometry(value, srid=4326)
    return value


class Feature(models.Model):
    """Features table for storing individual geospatial features."""

    id = models.AutoField(primary_key=True)
    shape = models.GeometryField(srid=4326)
    # A single point standing in for the feature. Defaults to the centroid of
    # `shape`, and is recomputed whenever `shape` changes unless a new point is
    # supplied in the same write. The rule is enforced by the
    # features_sync_representative_point trigger (migration 0009) so it holds
    # for QuerySet.update() and raw SQL too; sync_representative_point() below
    # mirrors it so in-memory instances match what the database stored.
    # spatial_index=False because the GIST index is declared in Meta.indexes
    # instead: that lets migration 0009 build it concurrently after the
    # backfill rather than inside AddField, where it would have made every
    # backfill update non-HOT (see database.md §3).
    representative_point = models.PointField(
        srid=4326, blank=True, null=True, spatial_index=False
    )

    objects = FeatureQuerySet.as_manager()

    class Meta:
        db_table = "features"
        indexes = [
            # Serves tile queries (representative_point && ST_TileEnvelope(...)).
            GistIndex(fields=["representative_point"], name="idx_features_repr_point"),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._snapshot_geometry()

    def __str__(self):
        return f"Feature {self.id}"

    def _snapshot_geometry(self):
        # Raw __dict__ values: reading the descriptors would fetch deferred
        # fields. Values loaded from the database are already GEOSGeometry.
        self._loaded_shape = self.__dict__.get("shape")
        self._loaded_point = self.__dict__.get("representative_point")

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self._snapshot_geometry()

    def sync_representative_point(self):
        """Apply the representative_point rule to this instance (see the field comment)."""
        if self.shape is None:
            return
        self.shape = _as_geometry(self.shape)
        shape_changed = (
            self._loaded_shape is not None
            and self.shape != _as_geometry(self._loaded_shape)
        )
        point_changed = self.representative_point != _as_geometry(self._loaded_point)
        if self.representative_point is None or (shape_changed and not point_changed):
            self.representative_point = self.shape.centroid

    def save(self, *args, **kwargs):
        self.sync_representative_point()
        super().save(*args, **kwargs)
        self._snapshot_geometry()


class FeatMap(models.Model):
    """Feature map table linking feature collections to individual features."""

    id = models.AutoField(primary_key=True)
    fc = models.ForeignKey(
        FeatureCollection, on_delete=models.CASCADE, db_column="fc_id"
    )
    geom = models.ForeignKey(Feature, on_delete=models.CASCADE, db_column="geom_id")
    name = models.CharField(max_length=200, blank=True, null=True)
    attr = models.JSONField(blank=True, null=True)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, blank=True, null=True, db_column="parent"
    )

    class Meta:
        db_table = "feat_map"
        constraints = [
            models.UniqueConstraint(
                fields=["fc", "geom"], name="feat_map_fc_geom_unique"
            )
        ]

    def __str__(self):
        return f"FeatMap {self.id}: {self.name or 'unnamed'}"


@receiver(pre_delete, sender=FeatureCollection)
def delete_features_on_fc_delete(sender, instance, **kwargs):
    """Delete Feature rows belonging to this collection before FeatMap CASCADE removes them."""
    geom_ids = list(FeatMap.objects.filter(fc=instance).values_list("geom_id", flat=True))
    Feature.objects.filter(id__in=geom_ids).delete()
