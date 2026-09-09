import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

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
    """Extract tasks table for managing data extraction jobs.

    resource_ids holds the DatasetResource ids this task covers: exactly one
    for a standard (ungrouped) task, N for a grouped task (e.g. 12 for a
    year-bucketed monthly dataset). Position i in resource_ids corresponds to
    position i in each ExtractData row's value arrays for this task -- see
    ExtractData below.
    """

    id = models.AutoField(primary_key=True)
    resource_ids = ArrayField(models.IntegerField())
    # Plain integer rather than ForeignKey(Dataset, ...): extract_tasks is
    # partitioned by dataset_id (see the partitioning migration), and a task's
    # dataset is already reachable via fm/po/resource_ids -- this column
    # exists for the partition key and fast filtering, not as the primary way
    # to navigate to a Dataset.
    dataset_id = models.IntegerField()
    task_group_period = models.CharField(max_length=10, null=True, blank=True)
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

    def __str__(self):
        return (
            f"ExtractTask {self.id}: Resources {self.resource_ids} - Status {self.status}"
        )


class ExtractTaskBuildProgress(models.Model):
    """Tracks how far build_extract_tasks has generated global-dataset tasks
    for each (resource, processing_option) pair.

    Global datasets cross every (resource, po) pair against the full feat_map
    table, which can run into the billions of candidate rows. Without this,
    every run re-scans the whole candidate space from scratch and has to
    anti-join past everything already inserted, so cost grows with how much
    work is already done rather than how much is left. completed_up_to_fm_id
    is the highest feat_map.id confirmed generated for that pair, so a run
    only has to look at feat_map rows added since.
    """

    resource = models.ForeignKey(
        DatasetResource, on_delete=models.CASCADE, db_column="resource_id"
    )
    po = models.ForeignKey(
        ProcessingOption, on_delete=models.CASCADE, db_column="po_id"
    )
    completed_up_to_fm_id = models.IntegerField(blank=True, null=True)
    # Set while a parallel worker is actively batching this pair, cleared
    # right after (success or failure). Only matters as crash recovery: if a
    # worker dies mid-pair, claim staleness lets another worker reclaim it
    # instead of waiting on it forever.
    claimed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "extract_task_build_progress"
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "po"],
                name="extract_task_build_progress_resource_po_unique",
            ),
        ]

    def __str__(self):
        return f"BuildProgress: Resource {self.resource_id} - PO {self.po_id} (up to fm {self.completed_up_to_fm_id})"


class ExtractData(models.Model):
    """Extract data table for storing extraction results.

    One row per (extract_task, name) -- see ExtractTask.resource_ids. Values
    are arrays position-aligned with the owning task's resource_ids: index i
    here is the result for resource_ids[i].

    Two independent levels of NULL, not to be conflated:
    - Column-level (float_values/int_values/str_values each nullable): only
      ONE of the three is actually used per row, matching data_column --
      exactly like the old scalar float_value/int_value/str_value columns
      this replaced, where a row's value had one type and the other two
      columns were simply irrelevant to it. The other two stay NULL, not an
      array of NULLs.
    - Element-level (each array's own field is null=True): within whichever
      one column is in use, a NULL at position i means resource_ids[i] still
      needs (re)processing -- see analytics.tasks.processing._run_extract_task.
    """

    extract_task = models.ForeignKey(
        ExtractTask, on_delete=models.CASCADE, db_column="extract_task_id"
    )
    dataset_id = models.IntegerField()
    name = models.CharField(max_length=100, blank=True, null=True)
    data_column = models.CharField(max_length=100, blank=True, null=True)
    float_values = ArrayField(models.FloatField(null=True), blank=True, null=True)
    int_values = ArrayField(models.BigIntegerField(null=True), blank=True, null=True)
    str_values = ArrayField(models.CharField(max_length=100, null=True), blank=True, null=True)

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

    data = models.JSONField(blank=True, null=True)

    # Account that owns this request. Set directly for authenticated
    # submissions; backfilled onto historical rows when a user verifies an
    # email address matching `contact` (see accounts.claims).
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requests",
        db_column="user_id",
    )

    class Meta:
        db_table = "requests"
        indexes = [
            # Claims and history lookups match contact case-insensitively.
            models.Index(Lower("contact"), name="requests_contact_lower_idx"),
        ]

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


class RequestToken(models.Model):
    """Magic-link tokens for email-based request history access."""

    token = models.CharField(max_length=64, unique=True, db_index=True)
    email = models.EmailField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "request_tokens"

    @classmethod
    def create_for_email(cls, email: str, expires_at) -> tuple["RequestToken", str]:
        """Create a token row and return (token_obj, raw_token).

        Only the hash is stored; raw_token must be sent to the user immediately
        and cannot be recovered later.
        """
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        obj = cls.objects.create(email=email, token=token_hash, expires_at=expires_at)
        return obj, raw

    @staticmethod
    def hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"RequestToken({self.email}, expires={self.expires_at.date()})"
