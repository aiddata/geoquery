from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.db.models import Count

from .models import Dataset, DatasetResource, Mapping


class MappingInline(admin.TabularInline):
    model = Mapping
    extra = 1


class DatasetResourceInline(admin.TabularInline):
    model = DatasetResource
    extra = 0
    fields = ("name", "label", "path", "temporal")


@admin.register(Dataset)
class DatasetAdmin(GISModelAdmin):
    list_display = (
        "name",
        "title",
        "type",
        "active",
        "public",
        "is_global",
        "mapped",
        "resource_count",
        "date_updated",
    )
    list_filter = ("active", "public", "is_global", "mapped", "type")
    search_fields = ("name", "title", "description", "tags")
    readonly_fields = ("date_added", "date_updated")
    inlines = [MappingInline, DatasetResourceInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "title",
                    "type",
                    "active",
                    "public",
                    "is_global",
                    "mapped",
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
                "fields": (
                    "description",
                    "details",
                    "variable_description",
                    "variable_factor",
                    "tags",
                ),
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
        return super().get_queryset(request).annotate(num_resources=Count("resources"))

    @admin.display(description="Resources", ordering="num_resources")
    def resource_count(self, obj):
        return obj.num_resources


@admin.register(Mapping)
class MappingAdmin(admin.ModelAdmin):
    list_display = ("dataset", "map_name", "map_val")
    list_filter = ("dataset",)
    search_fields = ("map_name", "dataset__name")
    raw_id_fields = ("dataset",)


@admin.register(DatasetResource)
class DatasetResourceAdmin(GISModelAdmin):
    list_display = ("name", "label", "dataset", "temporal")
    list_filter = ("dataset",)
    search_fields = ("name", "label", "dataset__name")
    raw_id_fields = ("dataset",)
