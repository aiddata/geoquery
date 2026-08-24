"""Tests for catalog-based access control.

The rule under test, from catalog.access:

    visible = active AND (public OR member of a catalog the caller can access)
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from guardian.models import GroupObjectPermission, UserObjectPermission
from guardian.shortcuts import assign_perm

from analytics.models import ProcessingOption
from catalog.access import (
    accessible_catalog_ids,
    filter_processing_options,
    resolve_feature_collection_for_tiles,
    visible_datasets,
    visible_feature_collections,
    visible_processing_options,
    visible_processing_options_for_dataset,
)
from catalog.models import Catalog
from datasets.models import Dataset
from features.models import FeatureCollection

User = get_user_model()


def make_fc(**kwargs):
    """Create a FeatureCollection without refreshing the matviews.

    features.signals fires refresh_materialized_views() on every non-upload
    FeatureCollection save, which issues three REFRESH MATERIALIZED VIEW
    statements per row created.
    """
    kwargs.setdefault("path", f"/data/boundaries/{kwargs['name']}.gpkg")
    with mock.patch("features.matviews.refresh_materialized_views"):
        return FeatureCollection.objects.create(**kwargs)


def make_dataset(**kwargs):
    kwargs.setdefault("path", f"/data/rasters/{kwargs['name']}")
    kwargs.setdefault("type", "raster")
    return Dataset.objects.create(**kwargs)


class AnonymousAccessTests(TestCase):
    """guardian's get_objects_for_user() swaps AnonymousUser for
    get_anonymous_user() unconditionally, which with ANONYMOUS_USER_NAME = None
    raises User.DoesNotExist. catalog.access must never reach that code path.
    """

    def setUp(self):
        self.public = make_dataset(name="pub", active=True, public=True)
        self.private = make_dataset(name="priv", active=True, public=False)

    def test_anonymous_user_returns_empty_without_raising(self):
        self.assertEqual(accessible_catalog_ids(AnonymousUser()), frozenset())

    def test_none_user_returns_empty_without_raising(self):
        # analytics.ingest models an anonymous submitter as user=None.
        self.assertEqual(accessible_catalog_ids(None), frozenset())

    def test_visible_datasets_for_anonymous_is_public_only(self):
        self.assertEqual(list(visible_datasets(AnonymousUser())), [self.public])

    def test_no_phantom_anonymous_user_row_exists(self):
        # Locks in ANONYMOUS_USER_NAME = None. accounts.User has a unique,
        # required email, so guardian's placeholder row would collide with the
        # next blank-email user and pollute allauth.
        self.assertFalse(User.objects.filter(username="AnonymousUser").exists())


class VisibilityTruthTableTests(TestCase):
    """One persona per method, against a fixed set of datasets."""

    def setUp(self):
        self.public = make_dataset(name="public", active=True, public=True)
        self.in_catalog = make_dataset(name="in-catalog", active=True, public=False)
        self.orphan = make_dataset(name="orphan", active=True, public=False)
        self.inactive = make_dataset(name="inactive", active=False, public=True)

        self.catalog = Catalog.objects.create(name="Internal")
        self.catalog.datasets.add(self.in_catalog)

        self.nobody = User.objects.create_user(
            username="nobody", email="nobody@example.com", password="x"
        )
        self.granted = User.objects.create_user(
            username="granted", email="granted@example.com", password="x"
        )
        assign_perm("catalog.access_catalog", self.granted, self.catalog)

        self.group_member = User.objects.create_user(
            username="grouped", email="grouped@example.com", password="x"
        )
        group = Group.objects.create(name="Partners")
        self.group_member.groups.add(group)
        assign_perm("catalog.access_catalog", group, self.catalog)

        self.superuser = User.objects.create_superuser(
            username="root", email="root@example.com", password="x"
        )

    def test_anonymous_sees_public_only(self):
        self.assertEqual(set(visible_datasets(AnonymousUser())), {self.public})

    def test_authenticated_without_grant_sees_public_only(self):
        self.assertEqual(set(visible_datasets(self.nobody)), {self.public})

    def test_direct_grant_adds_catalog_members(self):
        self.assertEqual(
            set(visible_datasets(self.granted)), {self.public, self.in_catalog}
        )

    def test_group_grant_adds_catalog_members(self):
        self.assertEqual(
            set(visible_datasets(self.group_member)), {self.public, self.in_catalog}
        )

    def test_superuser_sees_every_catalogued_dataset(self):
        # with_superuser=True is guardian's default and we keep it, so a
        # superuser is a poor choice for smoke-testing the gate.
        self.assertEqual(
            set(visible_datasets(self.superuser)), {self.public, self.in_catalog}
        )

    def test_inactive_is_never_visible(self):
        for user in (AnonymousUser(), self.nobody, self.granted, self.superuser):
            self.assertNotIn(self.inactive, visible_datasets(user))

    def test_private_dataset_in_no_catalog_is_visible_to_nobody(self):
        """Superuser bypass applies to *catalogs*, not to the public flag.

        get_objects_for_user hands a superuser every catalog id, but a dataset
        belonging to none of them still fails `public OR member of a catalog`.
        So a non-public dataset that nobody catalogued is unreachable through
        the API for everyone, superusers included -- it is only visible in the
        Django admin. Give it a catalog (or set public=True) to expose it.
        """
        for user in (AnonymousUser(), self.nobody, self.granted, self.superuser):
            self.assertNotIn(self.orphan, visible_datasets(user))


class NoDuplicateRowsTest(TestCase):
    """Locks in the pk__in=<subquery> formulation.

    Rewriting _public_or_catalog_q as Q(catalogs__in=[...]) joins the resource
    table to the m2m table, so a resource in two accessible catalogs comes back
    twice unless every call site remembers .distinct().
    """

    def test_dataset_in_two_granted_catalogs_appears_once(self):
        dataset = make_dataset(name="shared", active=True, public=False)
        user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        for name in ("A", "B"):
            catalog = Catalog.objects.create(name=name)
            catalog.datasets.add(dataset)
            assign_perm("catalog.access_catalog", user, catalog)

        results = list(visible_datasets(user))
        self.assertEqual(results, [dataset])
        self.assertEqual(visible_datasets(user).count(), 1)


class PermissionCleanupTests(TestCase):
    def test_deleting_catalog_removes_user_and_group_grants(self):
        catalog = Catalog.objects.create(name="Temporary")
        catalog_pk = catalog.pk
        user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        group = Group.objects.create(name="Partners")
        user.groups.add(group)
        assign_perm("catalog.access_catalog", user, catalog)
        assign_perm("catalog.access_catalog", group, catalog)

        content_type = ContentType.objects.get_for_model(Catalog)
        permission_filter = {
            "content_type": content_type,
            "object_pk": str(catalog_pk),
        }
        self.assertTrue(
            UserObjectPermission.objects.filter(**permission_filter).exists()
        )
        self.assertTrue(
            GroupObjectPermission.objects.filter(**permission_filter).exists()
        )

        catalog.delete()

        self.assertFalse(
            UserObjectPermission.objects.filter(**permission_filter).exists()
        )
        self.assertFalse(
            GroupObjectPermission.objects.filter(**permission_filter).exists()
        )

        replacement = Catalog.objects.create(pk=catalog_pk, name="Replacement")
        self.assertFalse(user.has_perm("catalog.access_catalog", replacement))


class ProcessingOptionWideningTests(TestCase):
    """Catalog membership on a ProcessingOption widens the option list for an
    already-visible dataset. It must never grant the dataset itself.
    """

    def setUp(self):
        self.public_ds = make_dataset(name="pub-ds", active=True, public=True)
        self.private_ds = make_dataset(name="priv-ds", active=True, public=False)

        self.public_po = ProcessingOption.objects.create(
            dataset=self.public_ds, short_name="mean", function="mean",
            active=True, public=True,
        )
        self.granted_po = ProcessingOption.objects.create(
            dataset=self.public_ds, short_name="max", function="max",
            active=True, public=False,
        )
        self.inactive_po = ProcessingOption.objects.create(
            dataset=self.public_ds, short_name="min", function="min",
            active=False, public=False,
        )
        # Lives on a dataset the user cannot see.
        self.po_on_private_ds = ProcessingOption.objects.create(
            dataset=self.private_ds, short_name="sum", function="sum",
            active=True, public=False,
        )

        self.catalog = Catalog.objects.create(name="Extra options")
        self.catalog.processing_options.add(
            self.granted_po, self.inactive_po, self.po_on_private_ds
        )
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        assign_perm("catalog.access_catalog", self.user, self.catalog)

    def test_granted_option_widens_visible_dataset(self):
        self.assertEqual(
            set(visible_processing_options_for_dataset(self.user, self.public_ds)),
            {self.public_po, self.granted_po},
        )

    def test_ungranted_user_sees_public_options_only(self):
        self.assertEqual(
            set(visible_processing_options_for_dataset(AnonymousUser(), self.public_ds)),
            {self.public_po},
        )

    def test_option_grant_does_not_reveal_its_dataset(self):
        self.assertNotIn(self.private_ds, visible_datasets(self.user))

    def test_option_on_invisible_dataset_is_not_visible(self):
        self.assertNotIn(self.po_on_private_ds, visible_processing_options(self.user))

    def test_inactive_option_stays_hidden_despite_grant(self):
        self.assertNotIn(
            self.inactive_po,
            visible_processing_options_for_dataset(self.user, self.public_ds),
        )

    def test_in_python_filter_agrees_with_queryset(self):
        # filter_processing_options backs the serializer's prefetched path, so
        # it must not drift from the ORM version.
        self.assertEqual(
            {po.id for po in filter_processing_options(
                self.user, self.public_ds.processing_options.all()
            )},
            {po.id for po in visible_processing_options_for_dataset(
                self.user, self.public_ds
            )},
        )


class TileVisibilityTests(TestCase):
    # The tile view reads geometry through the "replica" alias. Under test that
    # alias is a MIRROR of "default" (see settings.DATABASES), so this only
    # satisfies Django's multi-database isolation guard.
    databases = {"default", "replica"}

    def setUp(self):
        self.public_fc = make_fc(name="pub-fc", active=True, public=True)
        self.private_fc = make_fc(name="priv-fc", active=True, public=False)
        self.upload_fc = make_fc(
            name="user_upload_abc", active=True, public=False, is_user_upload=True
        )
        self.inactive_fc = make_fc(name="dead-fc", active=False, public=True)

        self.catalog = Catalog.objects.create(name="Boundaries")
        self.catalog.feature_collections.add(self.private_fc)
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        assign_perm("catalog.access_catalog", self.user, self.catalog)

    def test_public_fc_resolves_for_anonymous(self):
        self.assertEqual(
            resolve_feature_collection_for_tiles(AnonymousUser(), "pub-fc"),
            self.public_fc,
        )

    def test_private_fc_is_denied_without_grant(self):
        self.assertIsNone(
            resolve_feature_collection_for_tiles(AnonymousUser(), "priv-fc")
        )

    def test_private_fc_resolves_with_grant(self):
        self.assertEqual(
            resolve_feature_collection_for_tiles(self.user, "priv-fc"), self.private_fc
        )

    def test_user_upload_still_served_by_unguessable_name(self):
        # Pre-existing behaviour, deliberately preserved: the request
        # visualization map needs these and the submitter is often anonymous.
        self.assertEqual(
            resolve_feature_collection_for_tiles(AnonymousUser(), "user_upload_abc"),
            self.upload_fc,
        )

    def test_inactive_and_unknown_resolve_to_none(self):
        self.assertIsNone(resolve_feature_collection_for_tiles(self.user, "dead-fc"))
        self.assertIsNone(resolve_feature_collection_for_tiles(self.user, "nope"))

    def test_tile_endpoint_runs_the_sql_and_marks_private_responses(self):
        """A 200 proves the reshuffled params still match each SQL builder --
        a mismatched count would raise from cursor.execute."""
        self.client.force_login(self.user)
        response = self.client.get("/api/features/tiles/priv-fc/2/1/1.mvt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("Cookie", response.get("Vary", ""))

    def test_tile_endpoint_at_high_zoom_uses_raw_sql_builder(self):
        # z >= 13 takes _mvt_sql_raw rather than the matviews.
        self.client.force_login(self.user)
        response = self.client.get("/api/features/tiles/priv-fc/13/100/100.mvt")
        self.assertEqual(response.status_code, 200)

    def test_denied_tile_returns_empty_body_without_cache_header(self):
        response = self.client.get("/api/features/tiles/priv-fc/2/1/1.mvt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertNotIn("no-store", response.get("Cache-Control", ""))

    def test_upload_tile_endpoint_runs_dynamic_simplify_builder(self):
        response = self.client.get("/api/features/tiles/user_upload_abc/2/1/1.mvt")
        self.assertEqual(response.status_code, 200)


class EndpointTests(TestCase):
    # Dataset, autocomplete and feature-id reads go to the "replica" alias.
    databases = {"default", "replica"}

    def setUp(self):
        self.public_ds = make_dataset(name="public-ds", active=True, public=True)
        self.private_ds = make_dataset(name="private-ds", active=True, public=False)
        self.public_po = ProcessingOption.objects.create(
            dataset=self.private_ds, short_name="mean", function="mean",
            active=True, public=True,
        )
        self.granted_po = ProcessingOption.objects.create(
            dataset=self.private_ds, short_name="max", function="max",
            active=True, public=False,
        )
        self.public_fc = make_fc(name="public-fc", active=True, public=True)
        self.private_fc = make_fc(name="private-fc", active=True, public=False)

        self.catalog = Catalog.objects.create(name="Internal")
        self.catalog.datasets.add(self.private_ds)
        self.catalog.feature_collections.add(self.private_fc)
        self.catalog.processing_options.add(self.granted_po)

        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        assign_perm("catalog.access_catalog", self.user, self.catalog)

    def test_dataset_list_excludes_private_for_anonymous(self):
        names = {d["name"] for d in self.client.get("/api/datasets/").json()}
        self.assertIn("public-ds", names)
        self.assertNotIn("private-ds", names)

    def test_dataset_list_includes_private_for_granted_user(self):
        self.client.force_login(self.user)
        names = {d["name"] for d in self.client.get("/api/datasets/").json()}
        self.assertIn("private-ds", names)

    def test_dataset_detail_404s_for_anonymous(self):
        self.assertEqual(self.client.get("/api/datasets/private-ds/").status_code, 404)

    def test_dataset_detail_widens_extract_types_for_granted_user(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/datasets/private-ds/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {t["short_name"] for t in response.json()["extract_types"]},
            {"mean", "max"},
        )

    def test_autocomplete_respects_grants(self):
        anon = {r["name"] for r in self.client.get("/api/features/autocomplete/").json()}
        self.assertNotIn("private-fc", anon)

        self.client.force_login(self.user)
        granted = {
            r["name"] for r in self.client.get("/api/features/autocomplete/").json()
        }
        self.assertIn("private-fc", granted)

    def test_feature_ids_respects_grants(self):
        url = f"/api/features/ids/?fc={self.private_fc.id}"
        self.assertEqual(self.client.get(url).json()["featureIds"], [])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_coverage_endpoint_respects_grants(self):
        body = {"featureIds": []}
        anon = self.client.post(
            "/api/datasets/coverage/", data=body, content_type="application/json"
        )
        self.assertNotIn("private-ds", {d["name"] for d in anon.json()})

        self.client.force_login(self.user)
        granted = self.client.post(
            "/api/datasets/coverage/", data=body, content_type="application/json"
        )
        self.assertIn("private-ds", {d["name"] for d in granted.json()})

    def test_submission_rejects_private_dataset_for_anonymous(self):
        response = self.client.post(
            "/api/analytics/requests/",
            data={
                "email": "someone@example.com",
                "featureIds": [1],
                "datasets": [{"datasetName": "private-ds"}],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Dataset 'private-ds' not found or not available.",
            response.json()["warnings"],
        )

    def test_submission_resolves_private_dataset_for_granted_user(self):
        # No extract tasks exist, so this still 400s -- but on the *later*
        # "no extract tasks" warning, proving the dataset itself resolved.
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/analytics/requests/",
            data={
                "email": "someone@example.com",
                "featureIds": [1],
                "datasets": [{"datasetName": "private-ds"}],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        warnings = response.json()["warnings"]
        self.assertNotIn("Dataset 'private-ds' not found or not available.", warnings)
        self.assertTrue(any("No extract tasks found" in w for w in warnings))

    def test_explore_available_rejects_unauthorized_fc_ids(self):
        response = self.client.get(
            f"/api/visualize/explore/available/?fc={self.private_fc.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_dataset_list_issues_one_guardian_query(self):
        """Membership is memoized on request.user, so serializing N datasets
        must not cost N permission lookups."""
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get("/api/datasets/")
        guardian_queries = [
            q for q in ctx.captured_queries
            if "guardian_userobjectpermission" in q["sql"]
        ]
        self.assertEqual(len(guardian_queries), 1)


class CsrfContractTest(TestCase):
    """force_login runs with enforce_csrf_checks=False, so none of the other
    endpoint tests catch this. /api/datasets/coverage/ authenticates the
    session now, which makes DRF enforce CSRF for logged-in callers -- the
    frontend must reach it through apiFetch, not a bare fetch.
    """

    # /api/datasets/coverage/ reads through the "replica" alias.
    databases = {"default", "replica"}

    def test_coverage_post_requires_csrf_token_when_logged_in(self):
        user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.post(
            "/api/datasets/coverage/",
            data={"featureIds": []},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_coverage_post_still_open_to_anonymous_callers(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            "/api/datasets/coverage/",
            data={"featureIds": []},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
