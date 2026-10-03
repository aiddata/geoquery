"""analytics.query_tags — attribution without breaking anything.

The whole point of this module is observability, so the overriding property
is that it must never be able to fail a query. Each test below either pins
that, or pins the cardinality discipline that keeps pg_stat_statements from
evicting the entries we are adding tags to find.
"""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from analytics.models import Request
from analytics.query_tags import _sanitize, tag_queries, tagged


class TagShapeTests(TestCase):
    def test_tag_is_prefixed_to_the_statement(self):
        with CaptureQueriesContext(connection) as ctx:
            with tag_queries("materialize"):
                Request.objects.filter(status=99).count()

        self.assertTrue(
            any(q["sql"].startswith("/* gq:materialize */") for q in ctx.captured_queries),
            [q["sql"][:60] for q in ctx.captured_queries],
        )

    def test_untagged_queries_are_untouched(self):
        with CaptureQueriesContext(connection) as ctx:
            Request.objects.filter(status=99).count()

        self.assertFalse(any("gq:" in q["sql"] for q in ctx.captured_queries))

    def test_tag_does_not_leak_past_the_block(self):
        """execute_wrapper is scoped to the block; a leak would mislabel every
        later query on this connection and multiply cardinality."""
        with tag_queries("materialize"):
            Request.objects.filter(status=99).count()

        with CaptureQueriesContext(connection) as ctx:
            Request.objects.filter(status=98).count()

        self.assertFalse(any("gq:" in q["sql"] for q in ctx.captured_queries))

    def test_nested_tags_do_not_double_prefix(self):
        """Two entries for one statement is the cardinality cost; two prefixes
        on one statement would be a third."""
        with CaptureQueriesContext(connection) as ctx:
            with tag_queries("outer"):
                with tag_queries("inner"):
                    Request.objects.filter(status=99).count()

        for q in ctx.captured_queries:
            self.assertEqual(q["sql"].count("/* gq:"), 1, q["sql"][:80])

    def test_decorator_form_tags_the_call(self):
        @tagged("materialize")
        def work():
            return Request.objects.filter(status=99).count()

        with CaptureQueriesContext(connection) as ctx:
            work()

        self.assertTrue(any("/* gq:materialize */" in q["sql"] for q in ctx.captured_queries))


class TagSafetyTests(TestCase):
    """Tags reach pg_stat_statements and the slow-query log, so they are
    sanitized rather than trusted."""

    def test_comment_terminator_cannot_be_injected(self):
        self.assertEqual(_sanitize("a*/ DROP TABLE x --"), "adroptablex--")

    def test_quotes_and_whitespace_are_stripped(self):
        self.assertEqual(_sanitize("a'b\"c d"), "abcd")

    def test_tag_is_length_capped(self):
        self.assertEqual(len(_sanitize("x" * 200)), 48)

    def test_case_is_normalised_so_one_workload_is_one_entry(self):
        self.assertEqual(_sanitize("Materialize"), "materialize")

    def test_empty_tag_is_a_no_op_rather_than_an_empty_comment(self):
        with CaptureQueriesContext(connection) as ctx:
            with tag_queries("!!!"):
                Request.objects.filter(status=99).count()

        self.assertFalse(any("gq:" in q["sql"] for q in ctx.captured_queries))


class TaggingNeverBreaksQueriesTests(TestCase):
    """The property that justifies shipping this to production."""

    def test_query_still_runs_when_the_wrapper_raises(self):
        import analytics.query_tags as qt

        original = qt._sanitize

        def exploding(_tag):
            # Returns a str so the tag passes the empty check, then detonates
            # inside the wrapper where the SQL is rewritten.
            class Bomb(str):
                def __add__(self, other):
                    raise RuntimeError("boom")

            return Bomb("materialize")

        qt._sanitize = exploding
        try:
            with tag_queries("materialize"):
                # Must not raise, and must return the real answer.
                self.assertEqual(Request.objects.filter(status=99).count(), 0)
        finally:
            qt._sanitize = original

    def test_results_are_identical_tagged_and_untagged(self):
        Request.objects.create(status=1, data={})
        untagged = Request.objects.filter(status=1).count()
        with tag_queries("materialize"):
            tagged_count = Request.objects.filter(status=1).count()

        self.assertEqual(untagged, tagged_count)
        self.assertEqual(tagged_count, 1)
