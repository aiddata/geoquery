from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.db.models import Count

from .models import (
    Coverage,
    ProcessingOption,
    ExtractTask,
    Request,
    RequestMap,
)


@admin.register(Coverage)
class CoverageAdmin(admin.ModelAdmin):
    list_display = ("dataset", "geom", "status")
    list_filter = ("dataset", "geom", "status")
    search_fields = ("dataset", "geom")
    raw_id_fields = ("dataset", "geom")


@admin.register(ProcessingOption)
class ProcessingOptionAdmin(admin.ModelAdmin):
    list_display = ("id", "short_name", "description")
    search_fields = ("id", "short_name", "description")


@admin.register(ExtractTask)
class ExtractTaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "priority",
        "submit_time",
        "start_time",
        "update_time",
        "complete_time",
    )
    list_filter = (
        "status",
        "priority",
        "submit_time",
        "start_time",
        "update_time",
        "complete_time",
    )
    search_fields = ("id",)


# ExtractData is intentionally NOT registered here: it now has a
# CompositePrimaryKey (dataset_id, extract_task, name) rather than a
# surrogate id, and Django 5.2's admin unconditionally refuses to register
# any model where `model._meta.is_composite_pk` is true (AdminSite.register
# raises ImproperlyConfigured, regardless of ModelAdmin configuration) --
# there is currently no ModelAdmin option to work around this, so an admin
# UI for this table is not available until Django adds support.


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "contact",
        "status",
        "submit_time",
        "prepare_time",
        "process_time",
        "complete_time",
    )
    list_filter = ("status", "submit_time")
    search_fields = ("id", "contact")


# @admin.register(RequestMap)
# class RequestMapAdmin(admin.ModelAdmin):
#     list_display = ("req_id", "task_id")
#     list_filter = ("req_id", "task_id")
#     search_fields = ("req_id", "task_id")
