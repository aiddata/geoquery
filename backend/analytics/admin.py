from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.db.models import Count

from .models import Coverage, ProcessingOption, ExtractTask, ExtractData, Request, RequestMap



@admin.register(Coverage)
class CoverageAdmin(admin.ModelAdmin):
    list_display = ("dataset", "geom", "status")
    list_filter = ("dataset", "geom", "status")
    search_fields = ("dataset", "geom")
    raw_id_fields = ("dataset", "geom")
