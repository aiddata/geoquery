"""The map payload: what the iframe is given to render."""

from django.test import TestCase, override_settings

from mcp_server.apps.map import MAP_APP_URI, build_map_payload
from mcp_server.data.selection import SelectionError

from .factories import World


class MapPayloadTests(TestCase):
    def setUp(self):
        self.world = World().fill().simplify()

    def build(self, **kwargs):
        kwargs.setdefault("boundaries", [self.world.fc.name])
        kwargs.setdefault("dataset", "esa_landcover")
        kwargs.setdefault("extract_type", "mean")
        return build_map_payload(None, **kwargs)

    def test_geojson_is_valid_and_carries_only_names(self):
        payload = self.build()

        collection = payload["geojson"]
        self.assertEqual(collection["type"], "FeatureCollection")
        self.assertEqual(len(collection["features"]), 2)
        for feature in collection["features"]:
            self.assertEqual(feature["geometry"]["type"], "Polygon")
            # Values travel in `values`, keyed by column, so switching column
            # in the iframe needs no new geometry.
            self.assertEqual(list(feature["properties"]), ["name"])

    def test_values_are_sent_for_every_mappable_column(self):
        payload = self.build()

        self.assertEqual(
            sorted(payload["values"]), ["esa_lc_2015.mean", "esa_lc_2020.mean"]
        )
        north = str(self.world.features[0].id)
        self.assertEqual(payload["values"]["esa_lc_2015.mean"][north], 10.0)

    def test_values_omit_features_with_no_number(self):
        payload = self.build()

        south = str(self.world.features[1].id)
        self.assertIn(south, payload["values"]["esa_lc_2015.mean"])
        self.assertNotIn(south, payload["values"]["esa_lc_2020.mean"])

    def test_first_column_is_active_by_default(self):
        self.assertEqual(self.build()["column"], "esa_lc_2015.mean")

    def test_column_argument_selects_the_active_one(self):
        self.assertEqual(
            self.build(column="esa_lc_2020.mean")["column"], "esa_lc_2020.mean"
        )

    def test_unknown_column_lists_the_real_ones(self):
        with self.assertRaises(SelectionError) as ctx:
            self.build(column="nope")

        self.assertIn("esa_lc_2015.mean", str(ctx.exception))

    def test_breaks_are_monotonic_and_span_the_data(self):
        payload = self.build(classes=4)

        breaks = payload["breaks"]
        self.assertEqual(len(breaks), 5)
        self.assertEqual(breaks, sorted(breaks))
        self.assertEqual(breaks[0], 10.0)
        self.assertEqual(breaks[-1], 20.0)

    def test_equal_classification_is_honoured(self):
        payload = self.build(classification="equal", classes=2)

        self.assertEqual(payload["classification"], "equal")
        self.assertEqual(payload["breaks"], [10.0, 15.0, 20.0])

    def test_unknown_classification_and_palette_degrade_rather_than_error(self):
        payload = self.build(classification="jenks", palette="Viridis")

        self.assertEqual(payload["classification"], "quantile")
        self.assertEqual(payload["palette"]["name"], "YlOrRd")
        self.assertEqual(len(payload["palette"]["colors"]), 5)

    def test_classes_are_clamped_to_a_drawable_range(self):
        self.assertEqual(self.build(classes=99)["classes"], 9)
        self.assertEqual(self.build(classes=1)["classes"], 2)

    def test_stats_describe_the_active_column_only(self):
        payload = self.build(column="esa_lc_2020.mean")

        self.assertEqual(payload["stats"], {"min": 14.0, "max": 14.0, "mean": 14.0, "n": 1})

    def test_columns_carry_their_year_and_partial_flag(self):
        payload = self.build()

        by_name = {c["name"]: c for c in payload["columns"]}
        self.assertEqual(by_name["esa_lc_2020.mean"]["temporal"], "2020")
        self.assertTrue(by_name["esa_lc_2020.mean"]["partial"])
        self.assertFalse(by_name["esa_lc_2015.mean"]["partial"])

    def test_bbox_covers_the_features(self):
        west, south, east, north = self.build()["bbox"]

        self.assertEqual((west, south), (0.0, 0.0))
        self.assertEqual((east, north), (3.0, 1.0))

    def test_basemap_endpoints_are_present(self):
        basemap = self.build()["basemap"]

        self.assertIn("{z}/{x}/{y}", basemap["tiles"])
        self.assertIn("{fontstack}", basemap["glyphs"])
        self.assertIn("Protomaps", basemap["attribution"])

    def test_viz_url_matches_the_rendered_styling(self):
        payload = self.build(palette="Blues", classification="equal")

        self.assertIn("palette=Blues", payload["viz_url"])
        self.assertIn("scheme=equal", payload["viz_url"])
        self.assertIn("col=esa_lc_2015.mean", payload["viz_url"])

    def test_attribution_is_present(self):
        payload = self.build()

        self.assertIn("ESA Land Cover", payload["attribution"]["text"])
        self.assertIn("geoBoundaries", payload["attribution"]["text"])

    @override_settings(MCP_MAP_MAX_FEATURES=1)
    def test_over_the_feature_cap_drops_geometry_and_says_so(self):
        payload = self.build()

        self.assertIsNone(payload["geojson"])
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["feature_count"], 2)
        # The summary and the link still describe the whole selection.
        self.assertIsNotNone(payload["stats"])
        self.assertIsNotNone(payload["viz_url"])

    @override_settings(MCP_MAP_MAX_BYTES=10)
    def test_over_the_byte_cap_drops_geometry_too(self):
        """A few thousand detailed coastlines blow the size limit long before
        the feature count does."""
        payload = self.build()

        self.assertIsNone(payload["geojson"])
        self.assertTrue(payload["truncated"])

    def test_include_geometry_false_returns_a_summary_only(self):
        payload = self.build(include_geometry=False)

        self.assertIsNone(payload["geojson"])
        self.assertFalse(payload["truncated"])

    def test_formula_column_becomes_the_active_one(self):
        payload = self.build(formula="[esa_lc_2020.mean] - [esa_lc_2015.mean]")

        self.assertTrue(payload["column"].startswith("~"))
        self.assertIn(payload["column"], payload["values"])

    def test_a_finished_request_can_be_mapped_by_id(self):
        request = self.world.make_request()

        payload = build_map_payload(None, request_id=str(request.id))

        self.assertEqual(payload["source"], "request")
        self.assertEqual(payload["title"], "Test export")
        self.assertEqual(payload["feature_count"], 2)

    def test_title_names_the_dataset_and_place(self):
        self.assertEqual(
            self.build()["title"], "ESA Land Cover — gB_v6_TST_ADM1"
        )


class MapAppResourceTests(TestCase):
    """The HTML the tool points at has to actually be there and be an app."""

    def test_app_html_is_readable_and_wires_the_host_callback(self):
        from mcp_server.tools.map import _APP_HTML

        html = _APP_HTML.read_text(encoding="utf-8")

        self.assertIn("app.ontoolresult", html)
        self.assertIn("maplibre-gl", html)
        self.assertIn("ext-apps", html)

    def test_every_external_url_is_version_pinned(self):
        """An unpinned CDN import would silently change the map -- and could
        change what runs inside the user's chat client."""
        import re

        from mcp_server.tools.map import _APP_HTML

        html = _APP_HTML.read_text(encoding="utf-8")
        unpkg = re.findall(r"https://unpkg\.com/([^\"'\s]+)", html)
        self.assertTrue(unpkg)
        for url in unpkg:
            self.assertIn("@", url.split("/", 1)[-1] if url.startswith("@") else url)

    def test_every_external_host_is_allowed_by_the_csp(self):
        import re

        from mcp_server.apps.map import APP_CONNECT_DOMAINS, APP_RESOURCE_DOMAINS
        from mcp_server.tools.map import _APP_HTML

        html = _APP_HTML.read_text(encoding="utf-8")
        allowed = {
            u.rstrip("/") for u in (*APP_RESOURCE_DOMAINS, *APP_CONNECT_DOMAINS)
        }
        hosts = {
            f"https://{h}" for h in re.findall(r"https://([a-z0-9.\-]+)", html)
        }
        # Links the user clicks through to are not fetched by the page, so
        # they are not CSP-relevant.
        hosts -= {"https://www.geoquery.org", "https://openstreetmap.org", "https://doi.org"}
        self.assertTrue(hosts)
        self.assertEqual(hosts - allowed, set())

    def test_the_tool_and_the_resource_agree_on_the_uri(self):
        from mcp_server.apps import map as map_app

        self.assertEqual(MAP_APP_URI, map_app.MAP_APP_URI)
        self.assertTrue(MAP_APP_URI.startswith("ui://"))
