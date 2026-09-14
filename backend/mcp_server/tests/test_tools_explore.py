"""The explore tools: catalog search, discovery, and get_data.

Tool bodies are plain functions taking a user, so they are called directly
here; only test_server.py stands a real server up.
"""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from guardian.shortcuts import assign_perm

from catalog.models import Catalog
from datasets.models import Dataset
from features.models import FeatureCollection
from mcp_server.data.selection import SelectionError
from mcp_server.tools.catalog import (
    _get_boundary,
    _get_citations,
    _get_dataset,
    _list_available_data,
    _search_boundaries,
    _search_datasets,
)
from mcp_server.tools.explore import _get_data, viz_url
from mcp_server.data.selection import resolve_selection

from .factories import World, make_dataset, make_fc

User = get_user_model()


class SearchBoundariesTests(TestCase):
    def setUp(self):
        self.world = World()
        make_fc(name="gB_v6_GHA_ADM2", title="Ghana ADM2", group_level=2)
        make_fc(name="gB_v6_GHA_ADM0", title="Ghana", group_level=0)

    def test_matches_on_title(self):
        payload = _search_boundaries(None, query="Ghana")

        self.assertEqual(
            {b["name"] for b in payload["boundaries"]},
            {"gB_v6_GHA_ADM2", "gB_v6_GHA_ADM0"},
        )

    def test_iso3_matches_the_delimited_code_not_a_bare_substring(self):
        make_fc(name="gB_GHANAISH_XXX_ADM1", title="Decoy")

        payload = _search_boundaries(None, iso3="gha")

        self.assertEqual(
            {b["name"] for b in payload["boundaries"]},
            {"gB_v6_GHA_ADM2", "gB_v6_GHA_ADM0"},
        )

    def test_level_narrows_to_one_administrative_level(self):
        payload = _search_boundaries(None, iso3="GHA", level=0)

        self.assertEqual([b["name"] for b in payload["boundaries"]], ["gB_v6_GHA_ADM0"])

    def test_limit_truncates_and_says_so(self):
        payload = _search_boundaries(None, limit=1)

        self.assertEqual(len(payload["boundaries"]), 1)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["total_matching"], 3)

    def test_results_carry_source_and_license(self):
        payload = _search_boundaries(None, query="Testland")

        self.assertEqual(payload["boundaries"][0]["source_name"], "geoBoundaries")
        self.assertEqual(payload["boundaries"][0]["license"], "CC BY 4.0")

    def test_private_boundary_is_hidden_from_anonymous_callers(self):
        FeatureCollection.objects.filter(name="gB_v6_GHA_ADM0").update(public=False)

        names = {b["name"] for b in _search_boundaries(None)["boundaries"]}

        self.assertNotIn("gB_v6_GHA_ADM0", names)

    def test_catalog_grant_reveals_it(self):
        FeatureCollection.objects.filter(name="gB_v6_GHA_ADM0").update(public=False)
        user = User.objects.create_user(username="u", email="u@x.test", password="x")
        catalog = Catalog.objects.create(name="c")
        catalog.feature_collections.add(
            FeatureCollection.objects.get(name="gB_v6_GHA_ADM0")
        )
        assign_perm("catalog.access_catalog", user, catalog)

        names = {b["name"] for b in _search_boundaries(user)["boundaries"]}

        self.assertIn("gB_v6_GHA_ADM0", names)

    def test_user_uploads_never_appear(self):
        make_fc(name="user_upload_abc123", is_user_upload=True, public=True)

        names = {b["name"] for b in _search_boundaries(None)["boundaries"]}

        self.assertNotIn("user_upload_abc123", names)


class GetBoundaryTests(TestCase):
    def setUp(self):
        self.world = World()

    def test_counts_features_and_previews_them(self):
        payload = _get_boundary(None, self.world.fc.name)

        self.assertEqual(payload["feature_count"], 2)
        self.assertEqual(
            [f["name"] for f in payload["features_preview"]],
            ["Northshire", "Southshire"],
        )
        self.assertEqual(
            payload["features_preview"][0]["feature_id"], self.world.features[0].id
        )

    def test_carries_full_attribution(self):
        payload = _get_boundary(None, self.world.fc.name)

        self.assertEqual(payload["license"], "CC BY 4.0")
        self.assertIn("geoBoundaries", payload["attribution"]["text"])

    def test_unknown_name_is_an_actionable_error(self):
        with self.assertRaises(SelectionError) as ctx:
            _get_boundary(None, "nope")

        self.assertIn("search_boundaries", str(ctx.exception))


class DatasetToolTests(TestCase):
    def setUp(self):
        self.world = World()

    def test_search_returns_license_and_temporal_range(self):
        payload = _search_datasets(None, query="land")

        (ds,) = payload["datasets"]
        self.assertEqual(ds["name"], "esa_landcover")
        self.assertEqual(ds["license"], "ESA CCI Data Policy")
        self.assertEqual(ds["temporal_range"], "2015–2020")

    def test_tag_filter(self):
        make_dataset(name="rain", title="Rainfall", tags=["climate"])

        payload = _search_datasets(None, tag="climate")

        self.assertEqual([d["name"] for d in payload["datasets"]], ["rain"])

    def test_detail_lists_extract_types_as_get_data_accepts_them(self):
        payload = _get_dataset(None, "esa_landcover")

        self.assertEqual(
            sorted(e["short_name"] for e in payload["extract_types"]),
            ["count", "mean"],
        )
        self.assertEqual(payload["resource_count"], 2)
        self.assertNotIn("resources", payload)

    def test_resources_only_when_asked(self):
        payload = _get_dataset(None, "esa_landcover", include_resources=True)

        self.assertEqual(
            [r["year"] for r in payload["resources"]], [2015, 2020]
        )
        self.assertFalse(payload["resources_truncated"])

    def test_private_dataset_is_hidden(self):
        Dataset.objects.filter(pk=self.world.dataset.pk).update(public=False)

        with self.assertRaises(SelectionError):
            _get_dataset(None, "esa_landcover")


class ListAvailableDataTests(TestCase):
    def setUp(self):
        self.world = World().fill()

    def test_ready_lists_datasets_with_completed_extracts(self):
        payload = _list_available_data(None, [self.world.fc.name])

        (entry,) = payload["ready"]
        self.assertEqual(entry["dataset"], "esa_landcover")
        self.assertEqual(entry["extract_types"], ["mean"])
        self.assertEqual(entry["resource_count"], 2)
        self.assertEqual(entry["license"], "ESA CCI Data Policy")

    def test_coverage_fraction_reflects_partial_processing(self):
        payload = _list_available_data(None, [self.world.fc.name])

        # Both districts have 2015 values, so every feature is covered.
        self.assertEqual(payload["ready"][0]["coverage_fraction"], 1.0)

    def test_coverage_fraction_below_one_when_features_are_unprocessed(self):
        from features.models import Feature, FeatMap

        from .factories import square

        FeatMap.objects.create(
            fc=self.world.fc,
            geom=Feature.objects.create(shape=square(10.0, 0.0)),
            name="Eastshire",
        )

        payload = _list_available_data(None, [self.world.fc.name])

        self.assertAlmostEqual(payload["ready"][0]["coverage_fraction"], 2 / 3, places=3)

    def test_requestable_holds_datasets_with_coverage_but_no_extracts(self):
        make_dataset(name="rain", title="Rainfall", is_global=True)

        payload = _list_available_data(None, [self.world.fc.name])

        self.assertEqual([d["name"] for d in payload["requestable"]], ["rain"])

    def test_a_ready_dataset_is_never_also_requestable(self):
        payload = _list_available_data(None, [self.world.fc.name])

        ready = {e["dataset"] for e in payload["ready"]}
        requestable = {d["name"] for d in payload["requestable"]}
        self.assertEqual(ready & requestable, set())

    def test_non_global_dataset_with_no_coverage_row_is_excluded(self):
        """Without this, every dataset in the catalog would be offered for
        every place, and an export of one would produce nothing."""
        make_dataset(name="elsewhere", title="Elsewhere", is_global=False)

        payload = _list_available_data(None, [self.world.fc.name])

        self.assertNotIn("elsewhere", {d["name"] for d in payload["requestable"]})

    def test_attribution_covers_boundaries_and_ready_datasets(self):
        payload = _list_available_data(None, [self.world.fc.name])

        self.assertIn("ESA Land Cover", payload["attribution"]["text"])
        self.assertIn("geoBoundaries", payload["attribution"]["text"])


class GetCitationsTests(TestCase):
    def setUp(self):
        self.world = World().fill()

    def test_lists_references_for_named_datasets_and_boundaries(self):
        payload = _get_citations(
            None, datasets=["esa_landcover"], boundaries=[self.world.fc.name]
        )

        self.assertIn("Defourny", payload["references"])
        self.assertIn("Runfola", payload["references"])
        self.assertIn("Goodman", payload["references"])

    def test_reports_what_has_no_citation_or_license(self):
        make_dataset(name="bare", title="Bare", citation=None, license=None)

        payload = _get_citations(None, datasets=["bare"])

        self.assertEqual(payload["missing_citation"], ["Bare"])
        self.assertEqual(payload["missing_license"], ["Bare"])

    def test_request_id_cites_everything_the_export_used(self):
        request = self.world.make_request()

        payload = _get_citations(None, request_id=str(request.id))

        self.assertIn("Defourny", payload["references"])
        self.assertIn("Runfola", payload["references"])

    def test_nothing_to_cite_is_an_actionable_error(self):
        with self.assertRaises(SelectionError) as ctx:
            _get_citations(None)

        self.assertIn("request_id", str(ctx.exception))


class GetDataTableTests(TestCase):
    def setUp(self):
        self.world = World().fill()

    def get(self, **kwargs):
        kwargs.setdefault("boundaries", [self.world.fc.name])
        kwargs.setdefault("dataset", "esa_landcover")
        kwargs.setdefault("extract_type", "mean")
        return _get_data(None, **kwargs)

    def test_returns_one_row_per_feature_with_the_selected_columns(self):
        payload = self.get()

        self.assertEqual(payload["source"], "explore")
        self.assertEqual(payload["total_rows"], 2)
        self.assertEqual(
            [c["name"] for c in payload["columns"]],
            ["esa_lc_2015.mean", "esa_lc_2020.mean"],
        )
        north = next(r for r in payload["rows"] if r["name"] == "Northshire")
        self.assertEqual(north["values"]["esa_lc_2015.mean"], 10.0)
        self.assertEqual(north["feature_id"], self.world.features[0].id)

    def test_partial_columns_are_flagged(self):
        payload = self.get()

        flags = {c["name"]: c["partial"] for c in payload["columns"]}
        self.assertFalse(flags["esa_lc_2015.mean"])
        self.assertTrue(flags["esa_lc_2020.mean"])

    def test_column_stats_ignore_missing_values(self):
        payload = self.get()

        self.assertEqual(
            payload["column_stats"]["esa_lc_2015.mean"],
            {"min": 10.0, "max": 20.0, "mean": 15.0, "n": 2},
        )
        self.assertEqual(payload["column_stats"]["esa_lc_2020.mean"]["n"], 1)

    def test_years_narrow_the_columns(self):
        payload = self.get(years=[2015])

        self.assertEqual([c["name"] for c in payload["columns"]], ["esa_lc_2015.mean"])

    def test_explicit_columns_are_honoured_exactly(self):
        payload = self.get(columns=["esa_lc_2020.mean"])

        self.assertEqual([c["name"] for c in payload["columns"]], ["esa_lc_2020.mean"])

    def test_unknown_column_lists_the_real_ones(self):
        with self.assertRaises(SelectionError) as ctx:
            self.get(columns=["nope"])

        self.assertIn("esa_lc_2015.mean", str(ctx.exception))

    def test_sorting_puts_nulls_last_in_both_directions(self):
        for descending in (False, True):
            with self.subTest(descending=descending):
                payload = self.get(sort_by="esa_lc_2020.mean", descending=descending)

                self.assertEqual(
                    [r["values"]["esa_lc_2020.mean"] for r in payload["rows"]],
                    [14.0, None],
                )

    def test_sorting_by_an_unreturned_column_is_rejected(self):
        with self.assertRaises(SelectionError):
            self.get(columns=["esa_lc_2015.mean"], sort_by="esa_lc_2020.mean")

    def test_search_filters_by_feature_name(self):
        payload = self.get(search="south")

        self.assertEqual([r["name"] for r in payload["rows"]], ["Southshire"])

    def test_paging_reports_the_full_total(self):
        payload = self.get(limit=1)

        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["total_rows"], 2)
        self.assertTrue(payload["truncated"])

        second = self.get(limit=1, offset=1)
        self.assertFalse(second["truncated"])

    @override_settings(MCP_RESULTS_MAX_ROWS=1)
    def test_limit_is_clamped_to_the_configured_maximum(self):
        payload = self.get(limit=500)

        self.assertEqual(payload["limit"], 1)
        self.assertEqual(len(payload["rows"]), 1)

    @override_settings(MCP_RESULTS_MAX_COLUMNS=1)
    def test_column_cap_reports_what_it_dropped(self):
        payload = self.get()

        self.assertEqual(len(payload["columns"]), 1)
        self.assertEqual(payload["columns_omitted"], 1)

    def test_formula_adds_a_column_and_survives_the_column_cap(self):
        with override_settings(MCP_RESULTS_MAX_COLUMNS=1):
            payload = self.get(formula="[esa_lc_2020.mean] - [esa_lc_2015.mean]")

        self.assertEqual(len(payload["columns"]), 1)
        self.assertTrue(payload["columns"][0]["name"].startswith("~"))
        values = [r["values"][payload["columns"][0]["name"]] for r in payload["rows"]]
        self.assertCountEqual(values, [4.0, None])

    def test_viz_url_carries_the_selection(self):
        payload = self.get()

        self.assertIn(f"fc={self.world.fc.id}", payload["viz_url"])
        self.assertIn("col=esa_lc_2015.mean", payload["viz_url"])

    def test_every_payload_carries_attribution(self):
        payload = self.get()

        self.assertIn("ESA Land Cover", payload["attribution"]["text"])
        self.assertIn("geoBoundaries", payload["attribution"]["text"])

    def test_finished_request_is_readable_by_id(self):
        request = self.world.make_request()

        payload = _get_data(None, request_id=str(request.id))

        self.assertEqual(payload["source"], "request")
        self.assertEqual(payload["total_rows"], 2)
        self.assertIn("ESA Land Cover", payload["attribution"]["text"])


class GetDataGeoJsonTests(TestCase):
    def setUp(self):
        self.world = World().fill().simplify()

    def get(self, **kwargs):
        kwargs.setdefault("boundaries", [self.world.fc.name])
        kwargs.setdefault("dataset", "esa_landcover")
        kwargs.setdefault("extract_type", "mean")
        kwargs["format"] = "geojson"
        return _get_data(None, **kwargs)

    def test_is_a_valid_feature_collection_with_real_geometry(self):
        collection = self.get()["geojson"]

        self.assertEqual(collection["type"], "FeatureCollection")
        self.assertEqual(len(collection["features"]), 2)
        for feature in collection["features"]:
            self.assertEqual(feature["type"], "Feature")
            self.assertIn("name", feature["properties"])
            self.assertEqual(feature["geometry"]["type"], "Polygon")
            self.assertTrue(feature["geometry"]["coordinates"][0])

    def test_geometry_is_lon_lat_within_the_fixture_extent(self):
        """The simplified tables store EPSG:3857; anything that forgets to
        transform back produces coordinates in the millions."""
        collection = self.get()["geojson"]

        for feature in collection["features"]:
            for lon, lat in feature["geometry"]["coordinates"][0]:
                self.assertGreaterEqual(lon, -1)
                self.assertLessEqual(lon, 4)
                self.assertGreaterEqual(lat, -1)
                self.assertLessEqual(lat, 2)

    def test_values_ride_along_in_properties(self):
        collection = self.get()["geojson"]

        north = next(
            f for f in collection["features"] if f["properties"]["name"] == "Northshire"
        )
        self.assertEqual(north["properties"]["esa_lc_2015.mean"], 10.0)

    def test_carries_a_top_level_attribution_member(self):
        collection = self.get()["geojson"]

        self.assertIn("attribution", collection)
        self.assertIn("ESA Land Cover", collection["attribution"]["text"])

    def test_is_json_serialisable(self):
        json.dumps(self.get()["geojson"])

    @override_settings(MCP_MAP_MAX_FEATURES=1)
    def test_over_the_cap_drops_geometry_but_keeps_every_feature(self):
        payload = self.get()

        self.assertTrue(payload["truncated"])
        self.assertTrue(payload["geometry_omitted"])
        self.assertEqual(len(payload["geojson"]["features"]), 2)
        for feature in payload["geojson"]["features"]:
            self.assertIsNone(feature["geometry"])
        self.assertIsNotNone(payload["viz_url"])


class VizUrlTests(TestCase):
    def setUp(self):
        self.world = World().fill()

    def test_explore_url_lists_fc_and_po_ids(self):
        selection = resolve_selection(
            None,
            boundaries=[self.world.fc.name],
            dataset="esa_landcover",
            extract_type="mean",
        )

        url = viz_url(selection, col="esa_lc_2015.mean", palette="Blues")

        self.assertIn(f"/viz/explore?fc={self.world.fc.id}", url)
        self.assertIn(f"po={self.world.pos['mean'].id}", url)
        self.assertIn("palette=Blues", url)

    def test_request_url_is_the_request_route(self):
        request = self.world.make_request()
        selection = resolve_selection(None, request_id=str(request.id))

        url = viz_url(selection, col="x")

        self.assertIn(f"/viz/{request.id}?col=x", url)

    def test_empty_parameters_are_dropped(self):
        selection = resolve_selection(None, request_id=str(self.world.make_request().id))

        self.assertNotIn("formula", viz_url(selection, col="x", formula=None))
