import uuid

from django.db import models

from datasets.models import Dataset, DatasetResource
from features.models import FeatMap, Feature


class Coverage(models.Model):
    """Coverage table linking features to datasets with status tracking."""

    geom = models.ForeignKey(Feature, on_delete=models.CASCADE, db_column="geom_id")
    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, db_column="dataset_id"
    )
    status = models.IntegerField()

    class Meta:
        db_table = "coverage"
        constraints = [
            models.UniqueConstraint(
                fields=["geom", "dataset"], name="coverage_geom_dataset_unique"
            )
        ]

    def __str__(self):
        return f"Coverage: Feature {self.geom_id} - Dataset {self.dataset_id} (Status: {self.status})"


class ProcessingOption(models.Model):
    """Processing options for datasets."""

    id = models.AutoField(primary_key=True)
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        db_column="dataset_id",
        related_name="processing_options",
    )
    short_name = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True, null=True)
    function = models.CharField(max_length=100)
    result_type = models.CharField(max_length=100, blank=True, null=True)
    kwargs = models.JSONField(blank=True, null=True)
    active = models.BooleanField(default=False)
    public = models.BooleanField(default=False)

    class Meta:
        db_table = "processing_options"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "function", "kwargs"],
                name="processing_options_dataset_function_kwargs_unique",
            ),
            models.UniqueConstraint(
                fields=["dataset", "short_name", "active"],
                name="processing_options_dataset_short_name_active_unique",
            ),
        ]

    def __str__(self):
        return f"{self.dataset.name}: {self.short_name}"


class ExtractTask(models.Model):
    """Extract tasks table for managing data extraction jobs."""

    id = models.AutoField(primary_key=True)
    resource = models.ForeignKey(
        DatasetResource, on_delete=models.CASCADE, db_column="resource_id"
    )
    fm = models.ForeignKey(FeatMap, on_delete=models.CASCADE, db_column="fm_id")
    po = models.ForeignKey(
        ProcessingOption, on_delete=models.CASCADE, db_column="po_id"
    )
    status = models.IntegerField(default=0)
    priority = models.IntegerField(default=0)
    submit_time = models.DateTimeField(auto_now_add=True)
    start_time = models.DateTimeField(blank=True, null=True)
    update_time = models.DateTimeField(blank=True, null=True)
    complete_time = models.DateTimeField(blank=True, null=True)
    attempts = models.IntegerField(default=0)
    error = models.CharField(max_length=100, blank=True, null=True)
    kwargs = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = "extract_tasks"
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "fm", "po"], name="extract_tasks_resource_fm_po_pk"
            ),
            models.UniqueConstraint(fields=["id"], name="extract_tasks_id_unique"),
        ]

    def __str__(self):
        return (
            f"ExtractTask {self.id}: Resource {self.resource_id} - Status {self.status}"
        )


class ExtractData(models.Model):
    """Extract data table for storing extraction results."""

    extract_task = models.ForeignKey(
        ExtractTask, on_delete=models.CASCADE, db_column="extract_task_id"
    )
    name = models.CharField(max_length=100, blank=True, null=True)
    data_column = models.CharField(max_length=100, blank=True, null=True)
    float_value = models.FloatField(blank=True, null=True)
    int_value = models.IntegerField(blank=True, null=True)
    str_value = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = "extract_data"

    def __str__(self):
        return f"ExtractData for Task {self.extract_task_id}: {self.name}"


class Request(models.Model):
    """Requests table for managing extraction requests."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=100, blank=True, null=True)
    contact = models.CharField(max_length=100, blank=True, null=True)
    contact_flag = models.BooleanField(default=False)
    comments_requested = models.BooleanField(default=False)
    custom_name = models.CharField(max_length=100, blank=True, null=True)
    info = models.TextField(blank=True, null=True)
    status = models.IntegerField(blank=True, null=True)
    priority = models.IntegerField(blank=True, null=True)
    submit_time = models.DateTimeField(auto_now_add=True)
    prepare_time = models.DateTimeField(blank=True, null=True)
    process_time = models.DateTimeField(blank=True, null=True)
    complete_time = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "requests"

    def __str__(self):
        return f"Request {self.id}: {self.custom_name or 'unnamed'}"


class RequestMap(models.Model):
    """Request map table linking requests to extract tasks."""

    request = models.ForeignKey(Request, on_delete=models.CASCADE, db_column="req_id")
    task = models.ForeignKey(ExtractTask, on_delete=models.CASCADE, db_column="task_id")

    class Meta:
        db_table = "request_map"

    def __str__(self):
        return f"RequestMap: Request {self.request_id} - Task {self.task_id}"
