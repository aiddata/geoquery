"""End-to-end checks against a real server and client.

Everything else in this package calls tool bodies directly. These tests go
through FastMCP itself, because some of what has to hold is a property of the
registration rather than of the function: which tools exist, what their schemas
hide, that the map app is advertised, and -- the one that would otherwise be
easy to regress -- that every data-bearing tool's *text* ends with its
attribution line.

TransactionTestCase because FastMCP runs sync tools in a worker thread, which
opens its own database connection; a plain TestCase wraps everything in a
transaction that thread would never see.
"""

import asyncio

from django.test import TransactionTestCase

from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_server.apps.map import MAP_APP_URI
from mcp_server.server import build_server

from .factories import World

# Every tool that hands back data or describes a resource. The attribution
# contract applies to all of them; list_my_requests is deliberately absent
# because it returns only the caller's own export list.
DATA_BEARING_TOOLS = {
    "search_boundaries",
    "get_boundary",
    "search_datasets",
    "get_dataset",
    "list_available_data",
    "get_citations",
    "get_data",
    "show_map",
    "preview_request",
    "get_request_status",
}


class ServerIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.world = World().fill().simplify()
        self.mcp = build_server(auth=None, user_resolver=lambda: None)

    def run_client(self, coro_fn):
        async def main():
            async with Client(self.mcp) as client:
                return await coro_fn(client)

        return asyncio.run(main())

    # ── surface ──────────────────────────────────────────────────────────────

    def test_every_planned_tool_is_registered(self):
        tools = self.run_client(lambda c: c.list_tools())

        self.assertEqual(
            {t.name for t in tools},
            DATA_BEARING_TOOLS | {"list_my_requests", "submit_request"},
        )

    def test_read_only_tools_say_so_and_submit_does_not(self):
        tools = {t.name: t for t in self.run_client(lambda c: c.list_tools())}

        for name in DATA_BEARING_TOOLS | {"list_my_requests"}:
            self.assertTrue(
                tools[name].annotations.read_only_hint, f"{name} should be read-only"
            )
        self.assertFalse(tools["submit_request"].annotations.read_only_hint)

    def test_injected_parameters_never_reach_the_model(self):
        """`user`, `_db` and `ctx` are resolved server-side; a model that saw
        them would try to fill them in."""
        tools = self.run_client(lambda c: c.list_tools())

        for tool in tools:
            properties = set((tool.input_schema or {}).get("properties", {}))
            self.assertEqual(properties & {"user", "_db", "ctx"}, set(), tool.name)

    def test_every_tool_has_a_description(self):
        tools = self.run_client(lambda c: c.list_tools())

        for tool in tools:
            self.assertTrue((tool.description or "").strip(), tool.name)

    def test_show_map_advertises_the_app_resource(self):
        tools = {t.name: t for t in self.run_client(lambda c: c.list_tools())}

        self.assertEqual(
            (tools["show_map"].meta or {}).get("ui", {}).get("resourceUri"),
            MAP_APP_URI,
        )

    def test_the_map_app_resource_is_served_with_the_app_mime_type(self):
        resources = self.run_client(lambda c: c.list_resources())

        by_uri = {str(r.uri): r for r in resources}
        self.assertEqual(
            by_uri[MAP_APP_URI].mime_type, "text/html;profile=mcp-app"
        )

    def test_resources_and_prompts_are_registered(self):
        resources = self.run_client(lambda c: c.list_resources())
        templates = self.run_client(lambda c: c.list_resource_templates())
        prompts = self.run_client(lambda c: c.list_prompts())

        self.assertIn("geoquery://boundary-presets", {str(r.uri) for r in resources})
        self.assertIn("geoquery://citing", {str(r.uri) for r in resources})
        self.assertIn(
            "geoquery://requests/{request_id}/results.csv",
            {str(t.uri_template) for t in templates},
        )
        self.assertEqual(
            {p.name for p in prompts},
            {"explore_place", "summarize_request", "cite_sources"},
        )

    def test_the_server_instructions_state_the_attribution_duty(self):
        # client.instructions rather than initialize_result.instructions:
        # the latter is None on a modern (server/discover) negotiation.
        async def read(client):
            return client.instructions

        instructions = self.run_client(read) or ""

        self.assertIn("license", instructions)
        self.assertIn("get_citations", instructions)
        self.assertIn("EXPLORE", instructions)
        self.assertIn("EXPORT", instructions)

    # ── behaviour ────────────────────────────────────────────────────────────

    def call(self, name, args=None):
        return self.run_client(lambda c: c.call_tool(name, args or {}))

    def test_a_full_explore_round_trip(self):
        boundaries = self.call("search_boundaries", {"query": "Testland"})
        name = boundaries.structured_content["boundaries"][0]["name"]

        available = self.call("list_available_data", {"boundaries": [name]})
        dataset = available.structured_content["ready"][0]["dataset"]

        data = self.call(
            "get_data",
            {"boundaries": [name], "dataset": dataset, "extract_type": "mean"},
        )

        self.assertEqual(data.structured_content["total_rows"], 2)

    def test_geojson_survives_the_wire(self):
        result = self.call(
            "get_data",
            {
                "boundaries": [self.world.fc.name],
                "dataset": "esa_landcover",
                "extract_type": "mean",
                "format": "geojson",
            },
        )

        collection = result.structured_content["geojson"]
        self.assertEqual(collection["type"], "FeatureCollection")
        self.assertIn("attribution", collection)
        self.assertEqual(collection["features"][0]["geometry"]["type"], "Polygon")

    def test_show_map_returns_structured_content_for_the_iframe(self):
        result = self.call(
            "show_map",
            {
                "boundaries": [self.world.fc.name],
                "dataset": "esa_landcover",
                "extract_type": "mean",
            },
        )

        payload = result.structured_content
        self.assertIn("values", payload)
        self.assertIn("breaks", payload)
        self.assertIn("basemap", payload)
        self.assertIsNotNone(payload["geojson"])

    def test_a_selection_error_reaches_the_model_as_a_readable_message(self):
        with self.assertRaises(ToolError) as ctx:
            self.call("get_data", {"boundaries": ["nope"], "dataset": "esa_landcover"})

        self.assertIn("search_boundaries", str(ctx.exception))

    def test_an_anonymous_caller_cannot_list_exports(self):
        with self.assertRaises(ToolError) as ctx:
            self.call("list_my_requests", {})

        self.assertIn("signed-in", str(ctx.exception))

    def test_the_results_csv_resource_leads_with_attribution(self):
        request = self.world.make_request()
        uri = f"geoquery://requests/{request.id}/results.csv"

        contents = self.run_client(lambda c: c.read_resource(uri))

        text = contents[0].text
        self.assertTrue(text.startswith("# Data retrieved from GeoQuery"))
        self.assertIn("# License: CC BY 4.0", text)
        self.assertIn("# Citation: Defourny", text)
        self.assertIn("feature_id,name,boundary,", text)
        self.assertIn("Northshire", text)

    def test_the_citing_resource_is_readable(self):
        contents = self.run_client(lambda c: c.read_resource("geoquery://citing"))

        self.assertIn("Citing GeoQuery", contents[0].text)

    def test_a_prompt_renders(self):
        result = self.run_client(
            lambda c: c.get_prompt("explore_place", {"place": "Ghana"})
        )

        self.assertIn("Ghana", result.messages[0].content.text)
        self.assertIn("search_boundaries", result.messages[0].content.text)


class ConnectionLifecycleTests(TransactionTestCase):
    """Every call must give its database connection back.

    FastMCP runs sync tools in a worker thread and Django's connections are
    per-thread, so a connection opened by a tool is only reachable from that
    same thread. Releasing it in a Depends() teardown looks right and does
    nothing (the teardown runs on the event loop) -- which leaks one Postgres
    connection per call until the server can no longer connect. Counted here
    rather than reasoned about, because the failure is invisible until
    production runs out of connections.
    """

    def setUp(self):
        self.world = World().fill()
        self.request = self.world.make_request()
        self.mcp = build_server(auth=None, user_resolver=lambda: None)

    @staticmethod
    def open_sessions() -> int:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
            return cursor.fetchone()[0]

    def call(self, name, args):
        async def main():
            async with Client(self.mcp) as client:
                return await client.call_tool(name, args)

        return asyncio.run(main())

    def read(self, uri):
        async def main():
            async with Client(self.mcp) as client:
                return await client.read_resource(uri)

        return asyncio.run(main())

    def test_repeated_tool_calls_leak_no_connections(self):
        args = {
            "boundaries": [self.world.fc.name],
            "dataset": "esa_landcover",
            "extract_type": "mean",
        }
        self.call("get_data", args)
        baseline = self.open_sessions()

        for _ in range(3):
            self.call("get_data", args)

        self.assertEqual(self.open_sessions(), baseline)

    def test_a_failing_tool_call_still_releases_its_connection(self):
        self.call("search_boundaries", {})
        baseline = self.open_sessions()

        for _ in range(3):
            with self.assertRaises(ToolError):
                self.call("get_data", {"boundaries": ["nope"], "dataset": "x"})

        self.assertEqual(self.open_sessions(), baseline)

    def test_resource_reads_leak_no_connections(self):
        uri = f"geoquery://requests/{self.request.id}/results.csv"
        self.read(uri)
        baseline = self.open_sessions()

        for _ in range(3):
            self.read(uri)

        self.assertEqual(self.open_sessions(), baseline)


class SubmitRequestOverTheWireTests(TransactionTestCase):
    """The consent gate, driven by a real client rather than a fake Context.

    The unit tests inject their own Context; this one proves FastMCP actually
    injects a live one, that the elicitation round trip completes over the
    protocol, and that nothing is created until the user answers.
    """

    def setUp(self):
        from allauth.account.models import EmailAddress
        from django.contrib.auth import get_user_model

        self.world = World()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        EmailAddress.objects.create(
            user=self.user, email="u@example.com", verified=True, primary=True
        )
        self.mcp = build_server(auth=None, user_resolver=lambda: self.user)

    def submit(self, handler):
        async def main():
            async with Client(self.mcp, elicitation_handler=handler) as client:
                return await client.call_tool(
                    "submit_request",
                    {
                        "boundary": self.world.fc.name,
                        "datasets": [
                            {"name": "esa_landcover", "extract_types": ["mean"]}
                        ],
                        "name": "Wire export",
                    },
                )

        return asyncio.run(main())

    def test_the_user_is_asked_and_the_export_is_created_on_yes(self):
        from unittest import mock

        from analytics.models import Request

        asked = []

        async def accept(message, response_type, params, context):
            asked.append(message)
            return {"confirm": True}

        with mock.patch("analytics.signals.chain"):
            result = self.submit(accept)

        self.assertEqual(len(asked), 1)
        self.assertIn("Testland ADM1", asked[0])
        self.assertIn("4 extractions", asked[0])
        request = Request.objects.get()
        self.assertEqual(request.source, "mcp")
        self.assertEqual(request.custom_name, "Wire export")
        self.assertEqual(result.structured_content["task_count"], 4)

    def test_nothing_is_created_on_no(self):
        from mcp.types import ElicitResult

        from analytics.models import ExtractTask, Request

        async def decline(message, response_type, params, context):
            return ElicitResult(action="decline")

        result = self.submit(decline)

        self.assertEqual(Request.objects.count(), 0)
        self.assertEqual(ExtractTask.objects.count(), 0)
        self.assertIn("Cancelled", result.content[0].text)


class AttributionContractTests(TransactionTestCase):
    """Every data-bearing tool's text must end with its attribution line.

    This is the one thing the whole attribution layer rests on: a model that
    is handed a number with no source beside it will present it with no
    source. Asserted here, once, over every such tool, so a new tool cannot
    quietly opt out.
    """

    def setUp(self):
        self.world = World().fill().simplify()
        self.request = self.world.make_request()
        self.mcp = build_server(auth=None, user_resolver=lambda: None)

    def call(self, name, args):
        async def main():
            async with Client(self.mcp) as client:
                return await client.call_tool(name, args)

        return asyncio.run(main())

    def cases(self):
        fc = self.world.fc.name
        selection = {"boundaries": [fc], "dataset": "esa_landcover", "extract_type": "mean"}
        return {
            "search_boundaries": {"query": "Testland"},
            "get_boundary": {"name": fc},
            "search_datasets": {"query": "land"},
            "get_dataset": {"name": "esa_landcover"},
            "list_available_data": {"boundaries": [fc]},
            "get_citations": {"datasets": ["esa_landcover"], "boundaries": [fc]},
            "get_data": selection,
            "show_map": selection,
            "preview_request": {
                "boundary": fc,
                "datasets": [{"name": "esa_landcover", "extract_types": ["mean"]}],
            },
            "get_request_status": {"request_id": str(self.request.id)},
        }

    def test_every_data_bearing_tool_ends_its_text_with_its_attribution(self):
        cases = self.cases()
        self.assertEqual(set(cases), DATA_BEARING_TOOLS)

        for name, args in cases.items():
            with self.subTest(tool=name):
                result = self.call(name, args)

                text = result.content[0].text
                attribution = result.structured_content["attribution"]
                self.assertTrue(
                    text.endswith(attribution["text"]),
                    f"{name} text does not end with its attribution line",
                )
                self.assertIn("GeoQuery", attribution["text"])

    def test_the_attribution_names_the_data_actually_returned(self):
        result = self.call(
            "get_data",
            {
                "boundaries": [self.world.fc.name],
                "dataset": "esa_landcover",
                "extract_type": "mean",
            },
        )

        text = result.content[0].text
        self.assertIn("ESA Land Cover (ESA CCI Data Policy)", text)
        self.assertIn("geoBoundaries (CC BY 4.0)", text)
