"""Central resource-visibility helpers.

Every public read and submit path resolves resources through this module, so
the rule

    active AND (public OR member of a catalog the caller can access)

lives in exactly one place. Grants are additive: ``public=True`` still means
"visible to everyone, including anonymous callers"; a catalog grant only ever
widens what a caller can see.

Celery tasks and management commands deliberately do *not* use these helpers --
they have no user context and must keep filtering on ``active`` alone.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from analytics.models import ProcessingOption
from datasets.models import Dataset
from features.models import FeatureCollection

from .models import Catalog

ACCESS_CODENAME = "access_catalog"
ACCESS_PERM = f"catalog.{ACCESS_CODENAME}"

_CATALOG_CACHE_ATTR = "_catalog_access_ids"
_PO_CACHE_ATTR = "_catalog_access_po_ids"


# -- Catalog resolution ------------------------------------------------------


def accessible_catalog_ids(user) -> frozenset[int]:
    """Ids of the catalogs ``user`` may access. Memoized on the user instance.

    The unauthenticated short-circuit is load-bearing, not an optimisation.
    With ``ANONYMOUS_USER_NAME = None``, guardian's ``get_objects_for_user()``
    still swaps ``AnonymousUser`` for ``get_anonymous_user()`` unconditionally
    (shortcuts.py: ``if user.is_anonymous: user = get_anonymous_user()``), which
    does ``User.objects.get(username=None)`` and raises ``User.DoesNotExist``.
    Guardian's own ``None`` guard covers only the ``has_perm`` path. Without
    this branch every anonymous request would be a 500.

    ``user`` may also be ``None`` -- ``analytics.ingest`` models an anonymous
    submitter that way.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()

    cached = getattr(user, _CATALOG_CACHE_ATTR, None)
    if cached is not None:
        return cached

    # Imported lazily so importing this module never pulls guardian in at
    # app-loading time.
    from guardian.shortcuts import get_objects_for_user

    ids = frozenset(
        get_objects_for_user(
            user,
            ACCESS_PERM,
            klass=Catalog.objects.all(),
            # Defaults kept deliberately:
            #   with_superuser=True     -> superusers see every catalog, so
            #                              always smoke-test with a normal user.
            #   accept_global_perms=True -> ticking catalog.access_catalog in
            #                              the *global* permission picker grants
            #                              access to ALL catalogs. That is a
            #                              useful "internal staff" switch, but
            #                              it is easy to do by accident.
        ).values_list("id", flat=True)
    )
    setattr(user, _CATALOG_CACHE_ATTR, ids)
    return ids


def clear_access_cache(user) -> None:
    """Drop the memoized ids. Needed only in tests and long-lived shells."""
    for attr in (_CATALOG_CACHE_ATTR, _PO_CACHE_ATTR):
        if hasattr(user, attr):
            delattr(user, attr)


def _public_or_catalog_q(user, m2m_field: str) -> Q:
    """``public=True`` OR pk is a member of one of the caller's catalogs.

    Written as ``pk__in=<subquery over Catalog>`` rather than
    ``catalogs__in=[...]`` so the resource table is never joined to the m2m
    table: a resource sitting in two accessible catalogs would otherwise come
    back twice and force ``.distinct()`` at every call site.

    The subquery is deliberately left unevaluated -- a catalog can hold
    thousands of feature collections, and inlining those ids would blow up the
    SQL.
    """
    catalog_ids = accessible_catalog_ids(user)
    if not catalog_ids:
        return Q(public=True)
    return Q(public=True) | Q(
        pk__in=Catalog.objects.filter(id__in=catalog_ids).values(m2m_field)
    )


# -- Datasets ----------------------------------------------------------------


def visible_datasets(
    user, queryset: QuerySet[Dataset] | None = None
) -> QuerySet[Dataset]:
    """Datasets the caller may list, retrieve, and submit extracts against."""
    qs = Dataset.objects.all() if queryset is None else queryset
    return qs.filter(active=True).filter(_public_or_catalog_q(user, "datasets"))


# -- Feature collections -----------------------------------------------------


def visible_feature_collections(
    user, queryset: QuerySet[FeatureCollection] | None = None
) -> QuerySet[FeatureCollection]:
    """Feature collections the caller may browse, select, and extract against.

    User-upload collections are ``active=True, public=False``, so they are
    excluded here unless someone deliberately adds one to a catalog. Tile
    serving has its own rule -- see ``resolve_feature_collection_for_tiles``.
    """
    qs = FeatureCollection.objects.all() if queryset is None else queryset
    return qs.filter(active=True).filter(
        _public_or_catalog_q(user, "feature_collections")
    )


def resolve_feature_collection_for_tiles(user, name: str):
    """Resolve a feature collection by name for the MVT endpoint.

    Returns the instance, or ``None`` if the caller may not see it. Returning
    the instance rather than a bool means the tile view gets both ``id`` (for
    the SQL) and ``is_user_upload`` (for the simplification branch) out of the
    single query it was already running.

    User-upload collections keep their pre-existing rule: never public, but
    served to anyone holding the unguessable ``user_upload_<uuid4>`` name,
    because the request-visualization map needs them and the submitter is
    frequently anonymous.
    """
    fc = (
        FeatureCollection.objects.filter(name=name, active=True)
        .only("id", "name", "public", "is_user_upload")
        .first()
    )
    if fc is None:
        return None
    if fc.public or fc.is_user_upload:
        return fc
    catalog_ids = accessible_catalog_ids(user)
    if not catalog_ids:
        return None
    granted = Catalog.objects.filter(
        id__in=catalog_ids, feature_collections=fc.id
    ).exists()
    return fc if granted else None


# -- Processing options ------------------------------------------------------


def visible_processing_options_for_dataset(
    user, dataset, queryset: QuerySet[ProcessingOption] | None = None
) -> QuerySet[ProcessingOption]:
    """Options offered for a dataset the caller has ALREADY been shown.

    Catalog membership of a processing option only *widens* the option list for
    an already-visible dataset; it never grants the dataset itself. The caller
    is responsible for having resolved ``dataset`` through ``visible_datasets``.
    """
    qs = ProcessingOption.objects.all() if queryset is None else queryset
    return qs.filter(dataset=dataset, active=True).filter(
        _public_or_catalog_q(user, "processing_options")
    )


def visible_processing_options(
    user, queryset: QuerySet[ProcessingOption] | None = None
) -> QuerySet[ProcessingOption]:
    """Every option the caller may see, across all datasets.

    Enforces the full rule including that the option's dataset is visible. Use
    this when the caller supplies bare option ids (the explore endpoints).
    """
    qs = ProcessingOption.objects.all() if queryset is None else queryset
    return qs.filter(active=True, dataset__in=visible_datasets(user)).filter(
        _public_or_catalog_q(user, "processing_options")
    )


def accessible_processing_option_ids(user) -> frozenset[int]:
    """Ids of catalog-granted options. Memoized on the user instance.

    Safe to materialize because ``processing_options`` is a small table. Backs
    the in-Python serializer path, which cannot use a queryset without
    defeating a prefetch.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()

    cached = getattr(user, _PO_CACHE_ATTR, None)
    if cached is not None:
        return cached

    catalog_ids = accessible_catalog_ids(user)
    if not catalog_ids:
        ids: frozenset[int] = frozenset()
    else:
        ids = frozenset(
            pk
            for pk in Catalog.objects.filter(id__in=catalog_ids).values_list(
                "processing_options", flat=True
            )
            if pk is not None
        )
    setattr(user, _PO_CACHE_ATTR, ids)
    return ids


def filter_processing_options(user, options) -> list[ProcessingOption]:
    """In-Python equivalent of the queryset helpers, for a prefetched relation.

    Chaining ``.filter()`` onto ``dataset.processing_options.all()`` would
    re-query and defeat the prefetch in ``DatasetDetailView``; iterating the
    cached list does not. Assumes the dataset itself has already been vetted.
    """
    granted = accessible_processing_option_ids(user)
    return [po for po in options if po.active and (po.public or po.id in granted)]
