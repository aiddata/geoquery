from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from .models import FeatMap, Feature, FeatureCollection


@admin.register(FeatureCollection)
class FeatureCollectionAdmin(GISModelAdmin):
    list_display = (
        "name",
        "title",
        "active",
        "public",
        "is_global",
        "group_name",
        "feature_count",
        "date_updated",
    )
    list_filter = ("active", "public", "is_global", "group_name", "group_class")
    search_fields = ("name", "title", "description", "tags")
    readonly_fields = ("date_added", "date_updated", "feature_count_detail")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "title",
                    "short_name",
                    "active",
                    "public",
                    "is_global",
                    "feature_count_detail",
                )
            },
        ),
        (
            "Paths & Files",
            {
                "fields": ("path", "file_extension", "file_mask"),
            },
        ),
        (
            "Description",
            {
                "fields": ("description", "details", "tags"),
            },
        ),
        (
            "Source",
            {
                "fields": (
                    "citation",
                    "source_name",
                    "source_url",
                    "ingest_src",
                ),
            },
        ),
        (
            "Temporal",
            {
                "fields": (
                    "temporal_start",
                    "temporal_end",
                    "temporal_name",
                    "temporal_type",
                ),
            },
        ),
        (
            "Grouping",
            {
                "fields": (
                    "group_name",
                    "group_title",
                    "group_class",
                    "group_level",
                ),
            },
        ),
        (
            "Spatial",
            {
                "fields": ("spatial_extent",),
            },
        ),
        (
            "Other",
            {
                "fields": ("other", "date_added", "date_updated"),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(num_features=Count("featmap"))

    @admin.display(description="Features", ordering="num_features")
    def feature_count(self, obj):
        count = obj.num_features
        url = reverse("admin:features_featmap_changelist") + f"?fc__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, count)

    @admin.display(description="Features")
    def feature_count_detail(self, obj):
        if not obj.pk:
            return "-"
        count = obj.featmap_set.count()
        url = reverse("admin:features_featmap_changelist") + f"?fc__id__exact={obj.pk}"
        return format_html('<a href="{}">View all {} features &rarr;</a>', url, count)


@admin.register(Feature)
class FeatureAdmin(GISModelAdmin):
    list_display = ("id",)
    search_fields = ("id",)


@admin.register(FeatMap)
class FeatMapAdmin(admin.ModelAdmin):
    list_display = ("id", "fc", "geom", "name")
    list_filter = ("fc",)
    search_fields = ("name", "fc__name")
    raw_id_fields = ("fc", "geom", "parent")
