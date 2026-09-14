"""Resolving tool arguments into a set of rows.

This is where visibility is enforced for every data-bearing tool, so the
negative cases matter as much as the positive ones.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from guardian.shortcuts import assign_perm

from catalog.models import Catalog
from datasets.models import Dataset
from features.models import FeatureCollection
from mcp_server.data.selection import (
    SelectionError,
    apply_formula,
    load_payload,
    resolve_selection,
    with_partial_flags,
)
from visualize.data import build_explore_data

from .factories import World

User = get_user_model()


class ResolveSelectionTests(TestCase):
    def setUp(self):
        self.world = World().fill()

    def resolve(self, **kwargs):
        kwargs.setdefault("boundaries", [self.world.fc.name])
        kwargs.setdefault("dataset", self.world.dataset.name)
        return resolve_selection(None, **kwargs)

    def test_resolves_boundaries_and_every_extract_type(self):
        selection = self.resolve()

        self.assertEqual(selection.fc_ids, [self.world.fc.id])
        self.assertEqual(selection.fc_names, [self.world.fc.name])
        self.assertCountEqual(
            selection.po_ids, [po.id for po in self.world.pos.values()]
        )
        self.assertIsNone(selection.resource_ids)
        self.assertEqual(selection.source, "explore")

    def test_extract_type_narrows_to_one_option(self):
        selection = self.resolve(extract_type="mean")

        self.assertEqual(selection.po_ids, [self.world.pos["mean"].id])

    def test_years_narrow_to_matching_resources(self):
        selection = self.resolve(years=[2020])

        self.assertEqual(selection.resource_ids, [self.world.resources[2020].id])

    def test_resources_narrow_by_name(self):
        selection = self.resolve(resources=["esa_lc_2015"])

        self.assertEqual(selection.resource_ids, [self.world.resources[2015].id])

    def test_unknown_year_errors_and_lists_what_is_available(self):
        with self.assertRaises(SelectionError) as ctx:
            self.resolve(years=[1999])

        self.assertIn("2015", str(ctx.exception))
        self.assertIn("2020", str(ctx.exception))

    def test_unknown_boundary_points_at_search_boundaries(self):
        with self.assertRaises(SelectionError) as ctx:
            self.resolve(boundaries=["nope"])

        self.assertIn("search_boundaries", str(ctx.exception))

    def test_unknown_extract_type_lists_the_real_ones(self):
        with self.assertRaises(SelectionError) as ctx:
            self.resolve(extract_type="median")

        self.assertIn("count", str(ctx.exception))
        self.assertIn("mean", str(ctx.exception))

    def test_missing_dataset_argument_is_an_actionable_error(self):
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(None, boundaries=[self.world.fc.name])

        self.assertIn("list_available_data", str(ctx.exception))

    def test_mixing_request_id_with_a_live_selection_is_rejected(self):
        with self.assertRaises(SelectionError) as ctx:
            self.resolve(request_id="whatever")

        self.assertIn("not both", str(ctx.exception))


class VisibilityTests(TestCase):
    """A selection may never reach past what catalog.access allows."""

    def setUp(self):
        self.world = World().fill()
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )

    def test_private_boundary_is_not_resolvable_anonymously(self):
        FeatureCollection.objects.filter(pk=self.world.fc.pk).update(public=False)

        with self.assertRaises(SelectionError):
            resolve_selection(
                None,
                boundaries=[self.world.fc.name],
                dataset=self.world.dataset.name,
            )

    def test_private_dataset_is_not_resolvable_anonymously(self):
        Dataset.objects.filter(pk=self.world.dataset.pk).update(public=False)

        with self.assertRaises(SelectionError):
            resolve_selection(
                None,
                boundaries=[self.world.fc.name],
                dataset=self.world.dataset.name,
            )

    def test_catalog_grant_opens_both(self):
        FeatureCollection.objects.filter(pk=self.world.fc.pk).update(public=False)
        Dataset.objects.filter(pk=self.world.dataset.pk).update(public=False)
        catalog = Catalog.objects.create(name="c")
        catalog.feature_collections.add(self.world.fc)
        catalog.datasets.add(self.world.dataset)
        assign_perm("catalog.access_catalog", self.user, catalog)

        selection = resolve_selection(
            self.user,
            boundaries=[self.world.fc.name],
            dataset=self.world.dataset.name,
        )

        self.assertEqual(selection.fc_ids, [self.world.fc.id])

    def test_missing_boundary_does_not_reveal_whether_it_exists(self):
        FeatureCollection.objects.filter(pk=self.world.fc.pk).update(public=False)

        with self.assertRaises(SelectionError) as hidden:
            resolve_selection(
                None, boundaries=[self.world.fc.name], dataset=self.world.dataset.name
            )
        with self.assertRaises(SelectionError) as absent:
            resolve_selection(
                None, boundaries=["does-not-exist"], dataset=self.world.dataset.name
            )

        self.assertEqual(
            str(hidden.exception).replace(self.world.fc.name, "X"),
            str(absent.exception).replace("does-not-exist", "X"),
        )


class RequestSelectionTests(TestCase):
    def setUp(self):
        self.world = World().fill()

    def test_finished_request_resolves_to_its_boundaries_and_datasets(self):
        request = self.world.make_request()

        selection = resolve_selection(None, request_id=str(request.id))

        self.assertEqual(selection.source, "request")
        self.assertEqual(selection.fc_names, [self.world.fc.name])
        self.assertEqual([d.name for d in selection.datasets], ["esa_landcover"])

    def test_unfinished_request_says_so_and_points_at_the_status_tool(self):
        request = self.world.make_request(status=0)

        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(None, request_id=str(request.id))

        self.assertIn("get_request_status", str(ctx.exception))

    def test_unknown_request_id_is_an_error_not_a_crash(self):
        with self.assertRaises(SelectionError):
            resolve_selection(None, request_id="not-a-uuid")


class LoadPayloadTests(TestCase):
    def setUp(self):
        self.world = World().fill()

    def test_explore_payload_has_a_column_per_resource(self):
        selection = resolve_selection(
            None,
            boundaries=[self.world.fc.name],
            dataset=self.world.dataset.name,
            extract_type="mean",
        )

        payload = load_payload(selection)

        self.assertEqual(
            payload["columns"], ["esa_lc_2015.mean", "esa_lc_2020.mean"]
        )
        self.assertEqual(len(payload["features"]), 2)

    def test_year_filter_reaches_the_sql(self):
        selection = resolve_selection(
            None,
            boundaries=[self.world.fc.name],
            dataset=self.world.dataset.name,
            years=[2015],
        )

        payload = load_payload(selection)

        self.assertEqual(payload["columns"], ["esa_lc_2015.mean"])

    def test_explore_view_behaviour_is_unchanged_without_a_resource_filter(self):
        """build_explore_data's new argument must not alter its old calls."""
        fc_ids = [self.world.fc.id]
        po_ids = [po.id for po in self.world.pos.values()]

        self.assertEqual(
            build_explore_data(fc_ids, po_ids),
            build_explore_data(fc_ids, po_ids, None),
        )

    def test_request_payload_reads_the_same_values(self):
        request = self.world.make_request()
        selection = resolve_selection(None, request_id=str(request.id))

        payload = load_payload(selection)

        self.assertEqual(
            payload["columns"], ["esa_lc_2015.mean", "esa_lc_2020.mean"]
        )


class PartialFlagTests(TestCase):
    def setUp(self):
        self.world = World().fill()
        self.payload = load_payload(
            resolve_selection(
                None,
                boundaries=[self.world.fc.name],
                dataset=self.world.dataset.name,
                extract_type="mean",
            )
        )

    def test_a_column_missing_for_some_features_is_flagged_partial(self):
        flags = with_partial_flags(self.payload)

        self.assertFalse(flags["esa_lc_2015.mean"])
        self.assertTrue(flags["esa_lc_2020.mean"])

    def test_a_column_missing_for_every_feature_is_not_partial(self):
        """Absent everywhere is a different problem from absent in patches,
        and mislabelling it 'partial' would hide the real one."""
        for record in self.payload["features"].values():
            record.pop("esa_lc_2020.mean", None)

        self.assertFalse(with_partial_flags(self.payload)["esa_lc_2020.mean"])


class ApplyFormulaTests(TestCase):
    def setUp(self):
        self.world = World().fill()
        self.payload = load_payload(
            resolve_selection(
                None,
                boundaries=[self.world.fc.name],
                dataset=self.world.dataset.name,
                extract_type="mean",
            )
        )

    def test_adds_a_column_named_for_the_formula(self):
        name = apply_formula(
            self.payload, "[esa_lc_2020.mean] - [esa_lc_2015.mean]"
        )

        self.assertEqual(name, "~[esa_lc_2020.mean] - [esa_lc_2015.mean]")
        self.assertIn(name, self.payload["columns"])

    def test_evaluates_per_feature_and_propagates_nulls(self):
        name = apply_formula(
            self.payload, "[esa_lc_2020.mean] - [esa_lc_2015.mean]"
        )

        values = sorted(
            (f.get(name) for f in self.payload["features"].values()),
            key=lambda v: (v is None, v),
        )
        # Northshire has both years (14 - 10); Southshire has only 2015.
        self.assertEqual(values, [4.0, None])

    def test_unknown_column_lists_the_available_ones(self):
        with self.assertRaises(SelectionError) as ctx:
            apply_formula(self.payload, "[nope] * 2")

        self.assertIn("esa_lc_2015.mean", str(ctx.exception))

    def test_unparseable_formula_reports_the_parse_error(self):
        with self.assertRaises(SelectionError) as ctx:
            apply_formula(self.payload, "[a] +")

        self.assertIn("Could not parse formula", str(ctx.exception))
