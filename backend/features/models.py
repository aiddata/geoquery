from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField


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
    description = models.CharField(max_length=1000, blank=True, null=True)
    details = models.CharField(max_length=1000, blank=True, null=True)
    tags = ArrayField(models.CharField(max_length=100), blank=True, null=True)
    citation = models.CharField(max_length=500, blank=True, null=True)
    source_name = models.CharField(max_length=100, blank=True, null=True)
    source_url = models.CharField(max_length=200, blank=True, null=True)
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

    class Meta:
        db_table = "feature_collections"

    def __str__(self):
        return self.name


class Feature(models.Model):
    """Features table for storing individual geospatial features."""

    id = models.AutoField(primary_key=True)
    shape = models.GeometryField(srid=4326)

    class Meta:
        db_table = "features"

    def __str__(self):
        return f"Feature {self.id}"


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
