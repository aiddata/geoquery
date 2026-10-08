import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import connections, models
from django.db.models import F, Func, JSONField, Q, Value
from django.db.models.functions import Lower, Now, Upper
from django.db.models.signals import pre_delete
from django.dispatch import receiver
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

    resource_ids_hash is a stored generated column (hashtext(resource_ids::
    text), computed value-for-value identical to a direct hashtext() call)
    that both resource_ids-keyed unique indexes below key on instead of the
    raw array: resource_ids can run up to 12 elements (~72 bytes/entry) for
    a grouped task, vs a fixed 4-byte hash, and resource_ids was the single
    largest index in the schema before this column existed (see migration
    0024). Postgres maintains it automatically on every insert/update --
    application code never writes to it directly.

    The expression can't literally be hashtext(resource_ids::text): Postgres
    marks the generic array-to-text cast (array_out) STABLE rather than
    IMMUTABLE (it can't assume every element type's output function is
    immutable, even though int4's always is), and a GENERATED column
    expression must be IMMUTABLE. migration 0024 works around this by
    defining extract_tasks_resource_ids_hash(integer[]), a tiny SQL function
    declared IMMUTABLE -- safe here specifically because int4[]::text has no
    locale/session-dependent behavior -- whose body is exactly
    hashtext($1::text). Func() below calls that function directly rather
    than reconstructing the cast+hashtext expression in Python, so this
    declaration matches what's actually in the database.

    id is bigint. It was an int4 AutoField until extract_tasks_id_seq ran out
    at 2,147,483,647 with ~483M tasks still to build; migration 0031 converts
    it (see database.md section 11). Ids already start above int4's range, so
    SQL that carries them must cast to bigint[], never int[].

    pair_id records which pair (ExtractTaskBuildProgress) a lease created this
    task for. It is provenance, not identity: requests create tasks with it
    NULL, and uniqueness still comes from the (dataset_id, po_id,
    resource_ids_hash, fm_id) index. Readers use it to tell a current grouped
    set from a retired one. Deliberately no index and no foreign key: it is
    only ever read alongside a row already found some other way, and pair rows
    are kept for as long as any task names them.
    """

    id = models.BigAutoField(primary_key=True)
    resource_ids = ArrayField(models.IntegerField())
    resource_ids_hash = models.GeneratedField(
        expression=Func(
            F("resource_ids"),
            function="extract_tasks_resource_ids_hash",
        ),
        output_field=models.IntegerField(),
        db_persist=True,
    )
    # Plain integer rather than ForeignKey(Dataset, ...): extract_tasks is
    # partitioned by dataset_id (see the partitioning migration), and a task's
    # dataset is already reachable via fm/po/resource_ids -- this column
    # exists for the partition key and fast filtering, not as the primary way
    # to navigate to a Dataset.
    dataset_id = models.IntegerField()
    task_group_period = models.CharField(max_length=10, null=True, blank=True)
    fm = models.ForeignKey(FeatMap, on_delete=models.CASCADE, db_column="fm_id")
    # extract_tasks_po_id_idx and the database foreign key were dropped in
    # migration 0031. Every lookup by po_id also names dataset_id and either
    # fm_id or the resource hash, which the unique indexes serve. Deleting an
    # option deletes its tasks in delete_option_tasks, not by ORM cascade.
    po = models.ForeignKey(
        ProcessingOption,
        on_delete=models.DO_NOTHING,
        db_column="po_id",
        db_constraint=False,
        db_index=False,
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
    pair_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        db_table = "extract_tasks"

    def __str__(self):
        return (
            f"ExtractTask {self.id}: Resources {self.resource_ids} - Status {self.status}"
        )


@receiver(pre_delete, sender=ProcessingOption)
def delete_option_tasks(sender, instance, using, **kwargs):
    """Delete an option's tasks, their results and request links, in one partition.

    The ORM cascade would look tasks up by po_id, which has no index, and
    delete them by id alone; both scan every partition. Naming the dataset
    prunes each statement to the option's own partition. Runs inside the
    deleting transaction, and only when the option is actually deleted.
    """
    with connections[using].cursor() as cursor:
        cursor.execute(
            """
            WITH doomed AS (
                SELECT id FROM extract_tasks WHERE dataset_id = %(dataset)s AND po_id = %(po)s
            ), results AS (
                DELETE FROM extract_data
                WHERE dataset_id = %(dataset)s AND extract_task_id IN (SELECT id FROM doomed)
            ), links AS (
                DELETE FROM request_map
                WHERE dataset_id = %(dataset)s AND task_id IN (SELECT id FROM doomed)
            )
            DELETE FROM extract_tasks WHERE dataset_id = %(dataset)s AND po_id = %(po)s
            """,
            {"dataset": instance.dataset_id, "po": instance.pk},
        )


class ExtractTaskBuildProgress(models.Model):
    """A pair: one immutable set of resources with one processing option, and
    its cursor over feat_map.

    For a standard (ungrouped) dataset, resource_ids is a 1-element array. For
    a grouped dataset it holds every resource in one UTC
    date_trunc(task_group_period, temporal) bucket, ascending. The array never
    changes after insert: when a bucket gains or loses a resource, sync retires
    this pair and inserts (or reactivates) the pair for the new set. Results
    are never relabelled from one set to another.

    cursor_fm_id means "accounted for", not "finished". Every eligible feature
    at or below it has a task row, sits in an outstanding lease, or belongs to
    an input scope whose durable rewind (extract_input_state.rewind_from, or
    the pending targeted reset in extract_invalid_items, which rewinds its
    pairs when published) is still pending. Anything that deletes a lease or a
    background task must leave one of those true.
    See analytics.tasks.leases for the claim that advances it and
    analytics.sync for the rewinds.

    current is False for retired pairs. Their rows are kept: tasks name them
    in pair_id, and an identical set can become current again (A -> B -> A),
    in which case its cursor restarts at 0. Dataset or option inactivity does
    not retire a pair; it only parks it.

    The model keeps its historical name and table, which is why it is not
    called ExtractPair: the builder that once filled it is gone, but its rows
    and their ids carry over.
    """

    resource_ids = ArrayField(models.IntegerField())
    po = models.ForeignKey(
        ProcessingOption, on_delete=models.CASCADE, db_column="po_id"
    )
    dataset_id = models.IntegerField()
    # The UTC date_trunc(task_group_period, temporal) of a grouped set; NULL
    # for a standard pair.
    bucket = models.DateField(blank=True, null=True)
    task_group_period = models.CharField(max_length=10, blank=True, null=True)
    current = models.BooleanField(default=False, db_default=False)
    priority = models.IntegerField(default=0, db_default=0)
    cursor_fm_id = models.IntegerField(default=0, db_default=0)
    last_error = models.CharField(max_length=200, blank=True, null=True)
    retry_after = models.DateTimeField(db_default=Now())
    # Moving average of a page's compute time per feature, which sizes this
    # pair's pages to fit their lease (analytics.tasks.leases). NULL until a
    # page has finished or timed out.
    seconds_per_feature = models.FloatField(blank=True, null=True)

    class Meta:
        db_table = "extract_task_build_progress"
        constraints = [
            models.UniqueConstraint(
                fields=["resource_ids", "po"],
                name="extract_task_build_progress_resource_ids_po_unique",
            ),
            models.UniqueConstraint(
                fields=["dataset_id", "po", "bucket"],
                condition=Q(current=True, bucket__isnull=False),
                name="extract_pairs_current_bucket_unique",
            ),
        ]

    def __str__(self):
        state = "current" if self.current else "retired"
        return f"Pair {self.id}: resources {self.resource_ids} x po {self.po_id} ({state}, cursor {self.cursor_fm_id})"


class ExtractTaskLease(models.Model):
    """One page of a pair's features, owned by one worker until it completes.

    The lease is the durable record that its fm_ids are accounted for even
    though the pair's cursor has moved past them and no task row exists yet.
    Completion inserts the terminal task rows and their results and deletes
    the lease in one transaction; nothing else may delete a lease except sync,
    when the pair is retired and the work is therefore obsolete.

    token changes on every assignment, takeover and return. Completion and
    every write a worker makes to its lease are fenced on the token it was
    assigned, under the lease's row lock, so exactly one of "old owner
    completes" and "someone else takes over" happens.

    leased_until detects lost ownership; retry_after schedules backoff. A
    takeover needs both to be due. input_generations holds the dataset and
    collection generations captured at assignment; completion requires the
    same generations, clean.
    """

    id = models.BigAutoField(primary_key=True)
    progress = models.ForeignKey(
        ExtractTaskBuildProgress, on_delete=models.CASCADE, db_column="progress_id"
    )
    dataset_id = models.IntegerField()
    resource_ids = ArrayField(models.IntegerField())
    po_id = models.IntegerField()
    task_group_period = models.CharField(max_length=10, blank=True, null=True)
    fm_ids = ArrayField(models.IntegerField())
    input_generations = models.JSONField(default=dict, db_default=Value({}, JSONField()))
    token = models.UUIDField()
    leased_at = models.DateTimeField(db_default=Now())
    leased_until = models.DateTimeField()
    retry_after = models.DateTimeField(db_default=Now())
    created_at = models.DateTimeField(db_default=Now())
    attempts = models.IntegerField(default=0, db_default=0)
    last_error = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = "extract_task_leases"
        indexes = [
            models.Index(fields=["leased_until"], name="extract_task_leases_due_idx"),
        ]

    def __str__(self):
        return f"Lease {self.id}: pair {self.progress_id}, {len(self.fm_ids)} features"


class CoverageProgress(models.Model):
    """How far coverage has been computed for one non-global dataset.

    Every feat_map row with an id at or below covered_up_to_fm_id has had its
    geometry tested against the dataset's extent (a coverage row with status 0
    or 1), unless its collection was dirty and holds a durable rewind below
    it. Leases of a non-global dataset never scan past this watermark, so a
    missing row means a cap of 0. Global datasets have no row.

    extent_hash is the md5 of the extent this progress was computed against.
    It is an audit check for drift, not how extent changes are delivered:
    those arrive through extract_input_state like every other input change.
    """

    dataset = models.OneToOneField(
        Dataset, on_delete=models.CASCADE, primary_key=True, db_column="dataset_id"
    )
    covered_up_to_fm_id = models.IntegerField(default=0, db_default=0)
    extent_hash = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "extract_coverage_progress"

    def __str__(self):
        return f"Coverage progress: dataset {self.dataset_id} up to fm {self.covered_up_to_fm_id}"


class ExtractInputState(models.Model):
    """Durable record of changes to one dataset's or one collection's inputs.

    Database triggers on the input tables (migration 0031) write these rows in
    the same transaction as the change, so ORM bulk writes and raw SQL are
    captured like everything else. A trigger increments generation, ORs in the
    pending flags, keeps the minimum rewind boundary, and clears the
    checkpoint, error and backoff. The scope is dirty while generation !=
    applied_generation; analytics.sync reconciles it in bounded chunks and
    only then sets applied_generation. Nothing else may clear a flag.

    Workers take FOR SHARE on the clean states their work depends on, and
    record the generations they saw. Completion requires the same generations,
    still clean, which is what stops work computed from pre-edit inputs from
    landing after an edit.

    epoch counts invalidations only: a change that makes stored results or
    in-flight work wrong (a reshaped feature, a new resource path, a whole
    dataset reset, a deleted feature). Work records the epochs it saw and
    rechecks them; additive changes (a new feature or resource, an activity
    flip) advance generation, which drives sync, but not epoch, so they never
    discard finished work.

    A row outlives its dataset or collection (a tombstone) until sync has
    finished reconciling the deletion, then sync deletes it. A missing row is
    an initialization error, never "clean".

    checkpoint keys: generation, phase, dataset_id, fm_id, task_id (and
    failures, for backoff).
    """

    KIND_DATASET = "dataset"
    KIND_COLLECTION = "collection"
    KIND_CHOICES = [(KIND_DATASET, "Dataset"), (KIND_COLLECTION, "Collection")]

    pk = models.CompositePrimaryKey("kind", "object_id")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    object_id = models.IntegerField()
    generation = models.BigIntegerField(default=0, db_default=0)
    applied_generation = models.BigIntegerField(default=0, db_default=0)
    epoch = models.BigIntegerField(default=0, db_default=0)
    rewind_from = models.IntegerField(blank=True, null=True)
    sync_pairs = models.BooleanField(default=False, db_default=False)
    reset_tasks = models.BooleanField(default=False, db_default=False)
    reset_coverage = models.BooleanField(default=False, db_default=False)
    bootstrap_pending = models.BooleanField(default=False, db_default=False)
    checkpoint = models.JSONField(default=dict, db_default=Value({}, JSONField()))
    updated_at = models.DateTimeField(db_default=Now())
    retry_after = models.DateTimeField(db_default=Now())
    last_error = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "extract_input_state"

    @property
    def dirty(self):
        return self.generation != self.applied_generation

    def __str__(self):
        state = "dirty" if self.dirty else "clean"
        return f"{self.kind} {self.object_id}: generation {self.generation} ({state})"


class ExtractInvalidItem(models.Model):
    """One input a pending targeted reset invalidates.

    Written by the capture triggers (migration 0031) next to the scope's
    mark, and deleted when sync publishes that scope. A ``feature`` item
    (collection scope) is a feat_map row whose geometry changed; a
    ``resource`` or ``option`` item (dataset scope) is one whose path or
    definition changed. Sync resets only the tasks these name, and readers
    and claims skip those tasks until then (the extract_valid_tasks view).
    Whole-dataset changes still use the scope's reset flags instead.
    """

    FEATURE = "feature"
    RESOURCE = "resource"
    OPTION = "option"

    pk = models.CompositePrimaryKey("scope_kind", "scope_id", "item_kind", "item_id")
    scope_kind = models.CharField(max_length=10, choices=ExtractInputState.KIND_CHOICES)
    scope_id = models.IntegerField()
    item_kind = models.CharField(max_length=10)
    item_id = models.IntegerField()

    class Meta:
        db_table = "extract_invalid_items"
        indexes = [models.Index(fields=["item_kind", "item_id"], name="extract_invalid_items_item_idx")]


class ExtractData(models.Model):
    """Extract data table for storing extraction results.

    One row per (extract_task, name) -- see ExtractTask.resource_ids.

    The row has two value paths. The array columns are position-aligned with
    the owning task's resource_ids: index i is the result for resource_ids[i].
    The scalar columns carry the single-value case, where resource_ids has
    exactly one element -- which every row in production currently is. Only
    one path is populated per row; the unused one stays NULL, which costs a
    null-bitmap bit rather than storage.

    Two independent levels of NULL, not to be conflated:
    - Column-level: only ONE value column is used per row. Which one is
      implied by which is non-NULL -- there is no discriminator column, and
      none is needed, because nothing requires the type of a NULL value.
      A row with every value column NULL is a nodata result: a complete
      record that the extraction ran and found nothing there.
    - Element-level (each array's own field is null=True): within whichever
      column is in use, a NULL at position i means nodata for
      resource_ids[i] -- a final answer, not a request to reprocess. (A
      position that failed also lands as NULL, but that task is status=-1
      and merge never reads it; see _run_extract_task.) Whether a task still
      needs work is a property of ExtractTask.status, not of this row: see
      analytics.tasks.processing._positions_needing_processing, which
      recomputes every position on a retry.

    Primary key is the natural (dataset_id, extract_task_id, name) tuple, not
    a surrogate id -- (extract_task, name) was always the real uniqueness
    constraint (confirmed: 0 duplicates in production data before this
    migration), and dataset_id must lead per Postgres's partition-key
    requirement for any PK/unique constraint on this LIST-partitioned table.
    Dropping the surrogate id removes its own now-redundant PK index
    entirely, rather than keeping it alongside a second uniqueness
    constraint that would give none of the storage benefit.
    """

    pk = models.CompositePrimaryKey("dataset_id", "extract_task", "name")
    extract_task = models.ForeignKey(
        ExtractTask, on_delete=models.CASCADE, db_column="extract_task_id"
    )
    dataset_id = models.IntegerField()
    name = models.CharField(max_length=100)
    # Single-value path: used when cardinality(resource_ids) == 1, which is
    # every non-grouped task. A 1-element array carries ~20 bytes of array
    # header before its payload -- for an 8-byte int8 or float8 that is ~29
    # bytes against 8, about 41% of the row. The same header overhead applies
    # to str_value, though the saving there varies with string length.
    # 713.7M of 713.7M production rows were 1-element when this was measured.
    int_value = models.BigIntegerField(blank=True, null=True)
    float_value = models.FloatField(blank=True, null=True)
    str_value = models.CharField(max_length=100, blank=True, null=True)
    # Grouped path: used when cardinality(resource_ids) > 1, position-aligned
    # with the owning task's resource_ids.
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
            # Upper rather than Lower: Django renders __iexact as
            # UPPER(x) = UPPER(y) on PostgreSQL (hardcoded in its postgresql
            # backend's lookup_cast), and an expression index is only eligible
            # when its expression matches the predicate's exactly. The former
            # lower(contact) index could never serve these lookups, so every
            # claim and history read sequentially scanned.
            models.Index(Upper("contact"), name="requests_contact_upper_idx"),
        ]

    def featmap_ids(self, using="default"):
        """FeatMap ids this request's extract tasks actually touched.

        Resolved one dataset partition at a time rather than by joining
        straight into extract_tasks. extract_tasks is LIST partitioned on
        dataset_id with PRIMARY KEY (dataset_id, id), so any join or filter
        that doesn't carry dataset_id can't seek the PK index (id is its
        second column) and scans every partition -- at request scale that
        runs for hours, and when it happens inside the completion sweep's
        per-request transaction it holds that request's row lock the whole
        time, stacking every later sweep pass behind it. RequestMap already
        carries dataset_id per row, so the grouping is free.

        ``using`` defaults to the primary rather than following
        ``self._state.db``: the results documentation (through
        ``feature_collections``) is built right after the sweep decides the
        request is complete, and must not read a standby that may not have
        caught up. Read-only viewers of finished results pass ``"replica"``
        explicitly.
        """
        from collections import defaultdict

        tasks_by_dataset = defaultdict(list)
        for task_id, dataset_id in RequestMap.objects.using(using).filter(
            request=self
        ).values_list("task_id", "dataset_id"):
            tasks_by_dataset[dataset_id].append(task_id)

        fm_ids = set()
        for dataset_id, ds_task_ids in tasks_by_dataset.items():
            fm_ids.update(
                ExtractTask.objects.using(using)
                .filter(dataset_id=dataset_id, id__in=ds_task_ids)
                .values_list("fm_id", flat=True)
                .distinct()
            )
        return fm_ids

    def feature_collections(self):
        """The FeatureCollections this request's extract tasks actually touched.

        ``data["feature_ids"]`` records what was *submitted*, which can include
        ids that produced no task; the join through RequestMap is what the
        results were really built from. Used wherever the request has to be
        attributed -- the results documentation, and the MCP server's
        ``attribution`` payloads.
        """
        from features.models import FeatureCollection

        return FeatureCollection.objects.filter(
            featmap__id__in=self.featmap_ids()
        ).distinct()

    def __str__(self):
        return f"Request {self.id}: {self.custom_name or 'unnamed'}"


class RequestMap(models.Model):
    """Request map table linking requests to extract tasks."""

    request = models.ForeignKey(Request, on_delete=models.CASCADE, db_column="req_id")
    task = models.ForeignKey(ExtractTask, on_delete=models.CASCADE, db_column="task_id")
    dataset_id = models.IntegerField()

    class Meta:
        db_table = "request_map"

    def __str__(self):
        return f"RequestMap: Request {self.request_id} - Task {self.task_id}"


class LegacyRequest(models.Model):
    """A completed request from the previous version of GeoQuery.

    Imported read-only by ``import_legacy_requests``. Deliberately a separate
    table rather than a flag on ``Request``: legacy rows must never reach the
    completion sweep, priority bumping, task materialization, ``RequestMap`` or
    the extract workers, and a separate table makes that true by construction
    instead of by a filter every one of those paths has to remember.

    Only completed requests are imported, so there is no status column -- the
    API reports "completed" for every row. ``prepare_time`` and
    ``process_time`` are not carried over: in 9,716 of the exported completed
    rows they precede ``submit_time``, so importing them would publish a
    timeline that contradicts itself.
    """

    # Mongo ObjectId hex from the old system, preserved so old references and
    # the copied zip filenames keep resolving.
    id = models.CharField(max_length=24, primary_key=True)
    contact = models.CharField(max_length=100)
    custom_name = models.CharField(max_length=100)
    submit_time = models.DateTimeField()
    complete_time = models.DateTimeField()

    boundary_title = models.CharField(max_length=100)
    boundary_name = models.CharField(max_length=64)
    boundary_group = models.CharField(max_length=32)

    # Denormalized for display so neither the list nor the detail endpoint has
    # to parse `data`. Release entries first, then raster.
    dataset_titles = ArrayField(models.CharField(max_length=200), default=list)
    dataset_count = models.SmallIntegerField(default=0)

    # release_data + raster_data verbatim, for provenance.
    data = models.JSONField()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="legacy_requests",
        db_column="user_id",
    )
    # auto_now, so this is the last run that wrote this row, not the first
    # import. The import command lists it in its update_fields precisely so a
    # re-import records that it ran.
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "legacy_requests"
        indexes = [
            # Ownership lookups match contact case-insensitively, mirroring
            # requests_contact_upper_idx on Request. See the note there for
            # why the expression is Upper.
            models.Index(Upper("contact"), name="legacy_contact_upper_idx"),
            models.Index(fields=["-submit_time"], name="legacy_submit_time_idx"),
        ]

    def __str__(self):
        return f"LegacyRequest {self.id}: {self.custom_name or 'unnamed'}"


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
