"""What a tool says in its text content block.

Every one of these is a fact a client reported missing from its side of the
connection: a model that is only shown ``content`` must still get the values,
the feature names and the dataset names the payload carries.
"""

import asyncio

from django.test import TestCase, TransactionTestCase
from fastmcp import Client

from mcp_server.server import build_server
from mcp_server.tools.common import fmt_number

from .factories import World, make_dataset


class FmtNumberTests(TestCase):
    def test_large_whole_numbers_are_never_scientific_notation(self):
        self.assertEqual(fmt_number(18054321.0), "18,054,321")

    def test_fractions_keep_useful_digits(self):
        self.assertEqual(fmt_number(0.4567891), "0.4568")

    def test_very_small_numbers_stay_readable(self):
        self.assertEqual(fmt_number(0.0000123), "1.23e-05")

    def test_missing_is_not_rendered_as_a_number(self):
        self.assertEqual(fmt_number(None), "n/a")


class ToolTextTests(TransactionTestCase):
    def setUp(self):
        self.world = World().fill().simplify()
        self.mcp = build_server(auth=None, user_resolver=lambda: None)

    def call(self, name, args=None):
        async def main():
            async with Client(self.mcp) as client:
                return await client.call_tool(name, args or {})

        return asyncio.run(main()).content[0].text

    def test_get_boundary_names_its_features_as_its_description_promises(self):
        text = self.call("get_boundary", {"name": self.world.fc.name})

        self.assertIn("Northshire", text)
        self.assertIn(f"[{self.world.features[0].id}]", text)
        self.assertIn("geoBoundaries", text)

    def test_list_available_data_names_the_requestable_datasets(self):
        make_dataset(name="worldpop", title="WorldPop")

        text = self.call("list_available_data", {"boundaries": [self.world.fc.name]})

        self.assertIn("1 more available by export", text)
        self.assertIn("worldpop", text)

    def test_show_map_summary_never_uses_scientific_notation(self):
        self.world.extract(
            self.world.fms[1],
            self.world.pos["mean"],
            self.world.resources[2020],
            18054321.0,
        )

        text = self.call(
            "show_map",
            {
                "boundaries": [self.world.fc.name],
                "dataset": "esa_landcover",
                "extract_type": "mean",
                "column": "esa_lc_2020.mean",
            },
        )

        self.assertIn("18,054,321", text)
        self.assertNotIn("e+07", text)
