from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField


class Dataset(models.Model):
    """Model representing a dataset in the GeoQuery system."""

    id = models.AutoField(primary_key=True)
    active = models.BooleanField(default=False)
    public = models.BooleanField(default=False)
    name = models.CharField(max_length=300, unique=True)
    path = models.CharField(max_length=200, unique=True)
    file_extension = models.CharField(max_length=10, blank=True, null=True)
    file_mask = models.CharField(max_length=100, blank=True, null=True)
    title = models.CharField(max_length=200, blank=True, null=True)
    short_name = models.CharField(max_length=100, blank=True, null=True)
    description = models.CharField(max_length=1000, blank=True, null=True)
    details = models.CharField(max_length=1000, blank=True, null=True)
    tags = ArrayField(
        models.CharField(max_length=100), blank=True, null=True, default=list
    )
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
    variable_description = models.CharField(max_length=500, blank=True, null=True)
    variable_factor = models.FloatField(blank=True, null=True)
    mapped = models.BooleanField(default=False)
    type = models.CharField(max_length=100)

    class Meta:
        db_table = "datasets"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Mapping(models.Model):
    """Model representing a mapping value for a dataset."""

    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name="mappings"
    )
    map_name = models.CharField(max_length=100, blank=True, null=True)
    map_val = models.IntegerField()

    class Meta:
        db_table = "mappings"
        unique_together = [["dataset", "map_val"]]
        ordering = ["dataset", "map_val"]

    def __str__(self):
        return f"{self.dataset.name}: {self.map_name} = {self.map_val}"


class DatasetResource(models.Model):
    """Model representing a resource associated with a dataset."""

    id = models.AutoField(primary_key=True)
    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name="resources"
    )
    name = models.CharField(max_length=200, unique=True)
    label = models.CharField(max_length=200, blank=True, null=True)
    path = models.CharField(max_length=200, unique=True)
    temporal = models.DateTimeField(blank=True, null=True)
    spatial_extent = models.GeometryField(blank=True, null=True)

    class Meta:
        db_table = "dataset_resources"
        ordering = ["name"]

    def __str__(self):
        return self.name
