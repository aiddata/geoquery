from datasets.models import Dataset
from features.models import FeatMap, FeatureCollection
from rest_framework import serializers


class PublicDatasetSerializer(serializers.ModelSerializer):
    bbox = serializers.SerializerMethodField()

    def get_bbox(self, obj):
        if obj.spatial_extent is None:
            return None
        xmin, ymin, xmax, ymax = obj.spatial_extent.extent
        return [xmin, ymin, xmax, ymax]

    class Meta:
        model = Dataset
        fields = [
            "name",
            "title",
            "description",
            "type",
            "tags",
            "source_name",
            "source_url",
            "license",
            "license_url",
            "citation",
            "temporal_name",
            "temporal_type",
            "temporal_start",
            "temporal_end",
            "date_updated",
            "bbox",
        ]


class PublicDatasetCategorySerializer(serializers.Serializer):
    tag = serializers.CharField()
    display = serializers.CharField()


class PublicDatasetCoverageRequestSerializer(serializers.Serializer):
    """Documentation-only: describes the request body for @extend_schema.

    Not used for runtime validation — PublicDatasetCoverageView does its own
    manual isinstance check. featureIds is optional here to match that
    view's real behavior: a missing/empty list returns all active, public
    datasets rather than a 400.
    """

    featureIds = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )


class PublicBoundarySerializer(serializers.ModelSerializer):
    bbox = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()

    def get_bbox(self, obj):
        if obj.spatial_extent is None:
            return None
        xmin, ymin, xmax, ymax = obj.spatial_extent.extent
        return [xmin, ymin, xmax, ymax]

    def get_tags(self, obj):
        # Normalize null to [] to match features.views.FeatureCollectionAutocompleteView.
        return obj.tags or []

    class Meta:
        model = FeatureCollection
        fields = [
            "name",
            "title",
            "short_name",
            "description",
            "bbox",
            "group_name",
            "group_title",
            "group_class",
            "group_level",
            "source_name",
            "source_url",
            "license",
            "license_url",
            "citation",
            "tags",
        ]


class PublicBoundaryDetailSerializer(PublicBoundarySerializer):
    """Same shape as PublicBoundarySerializer plus the boundary's member Feature IDs.

    feature_ids resolves via FeatMap against `obj` — the model instance
    RetrieveAPIView.get_object() already resolved from an active+public
    filtered queryset, so no need to repeat those filters here (see
    PublicBoundaryDetailView.get_queryset()).
    """

    feature_ids = serializers.SerializerMethodField()

    def get_feature_ids(self, obj):
        # No .distinct() needed: FeatMap has a DB-level UniqueConstraint on
        # (fc, geom), so filtering to a single fc already guarantees unique
        # geom_id values. Read from a standby: tens of thousands of rows for
        # an ADM2 set, and membership changes only on ingest.
        return list(
            FeatMap.objects.using("replica")
            .filter(fc=obj)
            .values_list("geom_id", flat=True)
        )

    class Meta(PublicBoundarySerializer.Meta):
        fields = PublicBoundarySerializer.Meta.fields + ["feature_ids"]


class PublicBoundaryPresetSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True, required=False)
    source_name = serializers.CharField(allow_null=True, required=False)
    group_class = serializers.CharField(allow_null=True, required=False)
    group_level = serializers.IntegerField(allow_null=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    any_tags = serializers.ListField(child=serializers.CharField(), required=False)
    exclude_tags = serializers.ListField(child=serializers.CharField(), required=False)
    # Other names the boundary search matches
    aliases = serializers.ListField(child=serializers.CharField(), required=False)
    # List presets: exact boundary set names; null for rule presets
    members = serializers.ListField(child=serializers.CharField(), allow_null=True, required=False)
    sort_order = serializers.IntegerField(required=False)


# ── Stats (GEO-98) ───────────────────────────────────────────────────────────
# A stable public shape over the hourly snapshot the /stats page reads
# (stats.builder). The snapshot's own layout can change with the page; these
# don't, so sites showing GeoQuery's figures keep working.


class PublicStatsRequestsSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Requests submitted to the current GeoQuery, in any state.")
    completed = serializers.IntegerField()
    pending = serializers.IntegerField(help_text="Submitted and waiting to start.")
    processing = serializers.IntegerField()
    error = serializers.IntegerField()
    earlier_versions = serializers.IntegerField(
        allow_null=True,
        help_text="Requests made with earlier versions of GeoQuery. Not included in the counts above.",
    )


class PublicStatsExtractsSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Results extracted or queued: one dataset over one boundary.")
    completed = serializers.IntegerField()
    pending = serializers.IntegerField()
    claimed = serializers.IntegerField(help_text="Picked up by a worker, not yet started.")
    processing = serializers.IntegerField()
    error = serializers.IntegerField()


class PublicStatsCatalogSerializer(serializers.Serializer):
    datasets = serializers.IntegerField(allow_null=True, help_text="Public datasets available.")
    boundary_sets = serializers.IntegerField(allow_null=True, help_text="Public boundary sets available.")
    boundary_features = serializers.IntegerField(
        allow_null=True,
        help_text="Features (areas) across those boundary sets; one in two sets counts twice.",
    )


class PublicStatsPeopleSerializer(serializers.Serializer):
    users = serializers.IntegerField(
        allow_null=True, help_text="Distinct requesters by email, across all versions of GeoQuery."
    )
    organizations = serializers.IntegerField(
        allow_null=True,
        help_text="Distinct email domains among them; a provider such as gmail.com counts once.",
    )


class PublicStatsTurnaroundSerializer(serializers.Serializer):
    days = serializers.IntegerField(help_text="Measured over requests completed in this many recent days.")
    count = serializers.IntegerField(help_text="Requests measured.")
    median_seconds = serializers.FloatField(allow_null=True, help_text="Median time from submission to completion.")
    p90_seconds = serializers.FloatField(allow_null=True, help_text="90th percentile time from submission to completion.")


class PublicStatsTopDatasetSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="As in /datasets/{name}/.")
    title = serializers.CharField()
    requests = serializers.IntegerField()


class PublicStatsTopBoundarySetSerializer(serializers.Serializer):
    name = serializers.CharField(allow_null=True, help_text="As in /boundaries/{name}/.")
    title = serializers.CharField()
    requests = serializers.IntegerField()


class PublicStatsSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField(
        allow_null=True, help_text="When these figures were computed. They're refreshed hourly."
    )
    requests = PublicStatsRequestsSerializer()
    extracts = PublicStatsExtractsSerializer()
    catalog = PublicStatsCatalogSerializer()
    people = PublicStatsPeopleSerializer()
    turnaround = PublicStatsTurnaroundSerializer(allow_null=True)
    top_datasets = PublicStatsTopDatasetSerializer(
        many=True, help_text="Public datasets in the most requests (current GeoQuery), most first."
    )
    top_boundary_sets = PublicStatsTopBoundarySetSerializer(
        many=True, help_text="Public boundary sets in the most requests (current GeoQuery), most first."
    )
    cutover = serializers.DateField(
        allow_null=True, help_text="Day of the current GeoQuery's first request; earlier versions before it."
    )


class PublicStatsPointSerializer(serializers.Serializer):
    date = serializers.CharField(help_text="YYYY-MM-DD, YYYY-MM or YYYY, by period.")
    count = serializers.IntegerField()


class PublicStatsTimeseriesSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField(allow_null=True)
    period = serializers.ChoiceField(choices=["day", "month", "year"])
    cutover = serializers.DateField(allow_null=True)
    requests_submitted = PublicStatsPointSerializer(many=True)
    requests_completed = PublicStatsPointSerializer(many=True)
    earlier_versions_submitted = PublicStatsPointSerializer(
        many=True, help_text="Requests made with earlier versions of GeoQuery, by submission date."
    )
    earlier_versions_completed = PublicStatsPointSerializer(many=True)
    extracts_completed = PublicStatsPointSerializer(many=True)


class PublicStatsStatusSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=["healthy", "backlogged", "delayed"],
        help_text=(
            "backlogged: the oldest unfinished request has waited longer than backlog_after_seconds. "
            "delayed: the hourly figures have stopped refreshing. If this endpoint can't be reached, "
            "treat GeoQuery as offline."
        ),
    )
    unfinished_requests = serializers.IntegerField(help_text="Requests submitted and not yet finished.")
    oldest_wait_seconds = serializers.IntegerField(help_text="How long the oldest unfinished request has waited.")
    backlog_after_seconds = serializers.IntegerField()
    snapshot_age_seconds = serializers.IntegerField(allow_null=True, help_text="Age of the hourly figures.")
    checked_at = serializers.DateTimeField()
