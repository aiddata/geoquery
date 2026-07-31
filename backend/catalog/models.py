from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from guardian.models import GroupObjectPermission, UserObjectPermission


class Catalog(models.Model):
    """A named bundle of resources that access is granted on as a unit.

    django-guardian object permissions are attached to ``Catalog`` instances
    only -- never to ``Dataset`` / ``FeatureCollection`` / ``ProcessingOption``
    directly. Granting on the resources themselves would mean one permission
    row per (user, resource) pair, and revoking access would be a bulk delete
    with no record of intent.

    Grants are *additive* to each resource's own ``public`` flag:

        visible = active AND (public OR member of a catalog the caller can access)

    so nothing that is public today stops being public. See ``catalog.access``
    for the query helpers that implement that rule -- it is defined in exactly
    one place and every gated call site goes through it.
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    # Guardian's default permission models point at objects through a
    # GenericForeignKey, which cannot enforce database-level cascades. These
    # reverse relations let Django's deletion collector remove both kinds of
    # grants when a Catalog is deleted.
    user_object_permissions = GenericRelation(
        UserObjectPermission,
        content_type_field="content_type",
        object_id_field="object_pk",
    )
    group_object_permissions = GenericRelation(
        GroupObjectPermission,
        content_type_field="content_type",
        object_id_field="object_pk",
    )

    # Explicit M2M per type rather than a GenericForeignKey: a GFK cannot be
    # joined through, so every visibility filter would degenerate into pulling
    # ids into Python. Supporting a new resource type costs one field.
    datasets = models.ManyToManyField(
        "datasets.Dataset", blank=True, related_name="catalogs"
    )
    feature_collections = models.ManyToManyField(
        "features.FeatureCollection", blank=True, related_name="catalogs"
    )
    processing_options = models.ManyToManyField(
        "analytics.ProcessingOption", blank=True, related_name="catalogs"
    )

    class Meta:
        ordering = ["name"]
        # Appended to the default add/change/delete/view perms, which the admin
        # still needs. Full string: "catalog.access_catalog".
        permissions = [("access_catalog", "Can access resources in this catalog")]

    def __str__(self):
        return self.name
