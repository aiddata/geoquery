from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html
from guardian.admin import GuardedModelAdmin
from guardian.forms import GroupObjectPermissionsForm, UserObjectPermissionsForm
from guardian.shortcuts import get_groups_with_perms, get_users_with_perms

from .access import ACCESS_CODENAME
from .models import Catalog

_ACCESS_CHOICE = [(ACCESS_CODENAME, "Can access resources in this catalog")]


class AccessOnlyUserPermissionsForm(UserObjectPermissionsForm):
    """Grant screen that offers only ``access_catalog``.

    Guardian's default form lists every permission on the model, which invites
    someone to hand out ``change_catalog`` while trying to hand out read access.
    """

    def get_obj_perms_field_choices(self):
        return _ACCESS_CHOICE


class AccessOnlyGroupPermissionsForm(GroupObjectPermissionsForm):
    def get_obj_perms_field_choices(self):
        return _ACCESS_CHOICE


@admin.register(Catalog)
class CatalogAdmin(GuardedModelAdmin):
    list_display = ("name", "dataset_count", "fc_count", "po_count")
    search_fields = ("name", "description")
    # Datasets and processing options number in the hundreds -- fine for a
    # multi-select. Feature collections are one row per country x admin level,
    # far too many to render as <option>s on every page load.
    filter_horizontal = ("datasets", "processing_options")
    autocomplete_fields = ("feature_collections",)
    readonly_fields = ("granted_to",)
    fieldsets = (
        (None, {"fields": ("name", "description", "granted_to")}),
        (
            "Members",
            {
                "fields": ("datasets", "feature_collections", "processing_options"),
                "description": (
                    "Membership is additive to each resource's own 'public' flag, "
                    "so adding a resource here never hides it from anyone. "
                    "Processing options only widen the option list for a dataset "
                    "the caller can already see &mdash; they never grant the "
                    "dataset itself."
                ),
            },
        ),
    )

    def get_obj_perms_manage_user_form(self, request):
        return AccessOnlyUserPermissionsForm

    def get_obj_perms_manage_group_form(self, request):
        return AccessOnlyGroupPermissionsForm

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                n_datasets=Count("datasets", distinct=True),
                n_fcs=Count("feature_collections", distinct=True),
                n_pos=Count("processing_options", distinct=True),
            )
        )

    @admin.display(description="Datasets", ordering="n_datasets")
    def dataset_count(self, obj):
        return obj.n_datasets

    @admin.display(description="Boundaries", ordering="n_fcs")
    def fc_count(self, obj):
        return obj.n_fcs

    @admin.display(description="Options", ordering="n_pos")
    def po_count(self, obj):
        return obj.n_pos

    @admin.display(description="Granted to")
    def granted_to(self, obj):
        if not obj.pk:
            return "Save the catalog first, then use 'Object permissions' to grant access."
        users = sorted(
            str(u)
            for u in get_users_with_perms(
                obj, with_group_users=False, only_with_perms_in=[ACCESS_CODENAME]
            )
        )
        groups = sorted(
            g.name for g in get_groups_with_perms(obj, only_with_perms_in=[ACCESS_CODENAME])
        )
        url = reverse("admin:catalog_catalog_permissions", args=[obj.pk])
        return format_html(
            "<div>Users: {}</div><div>Groups: {}</div>"
            '<div style="margin-top:.5em"><a href="{}">Manage object permissions &rarr;</a></div>',
            ", ".join(users) or "—",
            ", ".join(groups) or "—",
            url,
        )
