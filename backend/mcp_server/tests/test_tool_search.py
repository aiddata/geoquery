"""Can a model find the right tool when its client loads tools on demand?

Clients with many tools connected (claude.ai among them) do not show the model
every tool definition up front. The model writes a search query, the client
ranks tool definitions against it, and only the top few are loaded. A tool
that loses that ranking costs the conversation an extra round trip -- or is
never called at all. This happened: a model searched "GeoQuery boundaries
available data" and got six tools back, none of them search_boundaries,
because its description said "boundary sets" and never said "GeoQuery".

We cannot run the client's ranker, so this ranks our own tool definitions with
BM25 -- the algorithm Anthropic's tool search offers -- over the same fields it
documents searching: name, description, and argument names and descriptions.
Tokenizing is deliberately unforgiving: no stemming, and a tool name such as
``search_boundaries`` is one token, not two. A description that ranks well
here is relying on the words people type, not on the ranker being clever.

The queries are written the way models write them. When one fails, fix the
description, not the query -- unless the query is genuinely unrealistic.
"""

import asyncio
import math
import re
from collections import Counter

from django.test import SimpleTestCase
from fastmcp import Client

from mcp_server.server import build_server

# A client typically loads three to five tools per search; passing at three
# leaves no margin to lose.
TOP_K = 3

# (query, the tool it must surface)
QUERIES = [
    # Finding a place is the first step of nearly every conversation.
    ("GeoQuery boundaries available data", "search_boundaries"),
    ("GeoQuery search_boundaries", "search_boundaries"),
    ("GeoQuery find boundaries for a place", "search_boundaries"),
    ("find administrative boundaries for a country", "search_boundaries"),
    ("look up district boundaries", "search_boundaries"),
    ("Nairobi Kenya city boundaries", "search_boundaries"),
    ("search region or province by name", "search_boundaries"),
    ("administrative area lookup ISO3 country code", "search_boundaries"),
    # The rest of the explore path.
    ("GeoQuery boundaries available data", "list_available_data"),
    ("what data is already processed for these boundaries", "list_available_data"),
    ("get data values table for districts", "get_data"),
    ("time series for one place across years", "get_data"),
    ("show choropleth map", "show_map"),
    ("visualize data on a map", "show_map"),
    # Catalog.
    ("search datasets catalog climate", "search_datasets"),
    ("dataset details extract types years", "get_dataset"),
    ("boundary set details feature count source license", "get_boundary"),
    ("cite sources references license", "get_citations"),
    # Export path.
    ("preview export what would be built", "preview_request"),
    ("submit export request download zip", "submit_request"),
    ("export progress status download link", "get_request_status"),
    ("list my previous exports", "list_my_requests"),
]


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def tool_document(tool) -> list[str]:
    parts = [tool.name, tool.description or ""]
    for name, schema in (tool.input_schema or {}).get("properties", {}).items():
        parts += [name, schema.get("description", "")]
    return tokenize(" ".join(parts))


def bm25_rank(query: str, documents: dict[str, list[str]], k1=1.2, b=0.75) -> list[str]:
    n = len(documents)
    avg_len = sum(len(d) for d in documents.values()) / n
    df = Counter(term for d in documents.values() for term in set(d))
    scores = {}
    for name, doc in documents.items():
        tf = Counter(doc)
        score = 0.0
        for term in set(tokenize(query)):
            if not tf[term]:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            norm = tf[term] + k1 * (1 - b + b * len(doc) / avg_len)
            score += idf * tf[term] * (k1 + 1) / norm
        scores[name] = score
    return sorted(scores, key=lambda name: -scores[name])


class ToolSearchRankingTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        async def list_tools():
            async with Client(build_server(auth=None, user_resolver=lambda: None)) as c:
                return await c.list_tools()

        cls.documents = {t.name: tool_document(t) for t in asyncio.run(list_tools())}

    def test_every_query_surfaces_its_tool(self):
        for query, expected in QUERIES:
            with self.subTest(query=query, expected=expected):
                ranking = bm25_rank(query, self.documents)
                self.assertIn(
                    expected,
                    ranking[:TOP_K],
                    f"{expected} ranked {ranking.index(expected) + 1}; "
                    f"top {TOP_K}: {ranking[:TOP_K]}",
                )

    def test_every_tool_is_covered_by_a_query(self):
        """A tool added without a query here has no protection at all."""
        self.assertEqual({tool for _, tool in QUERIES}, set(self.documents))
