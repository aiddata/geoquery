"""The export tools, and the consent gate in front of submit_request.

submit_request is the one thing this server creates, so the tests that matter
most are the ones proving it does *not* create: no Request before the user
answers, none when they decline, and none when the arguments changed after
they agreed.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from allauth.account.models import EmailAddress

from analytics.models import ExtractTask, Request
from mcp_server.data.selection import SelectionError
from mcp_server.tools.requests import (
    _accepted,
    _get_request_status,
    _list_my_requests,
    _plan_hash,
    _preview_request,
    _to_web_spec,
)

from .factories import World

User = get_user_model()


class DatasetSpecTranslationTests(TestCase):
    def test_snake_case_becomes_the_web_submission_shape(self):
        self.assertEqual(
            _to_web_spec(
                {
                    "name": "esa_landcover",
                    "extract_types": ["mean"],
                    "resources": ["esa_lc_2020"],
                    "kwargs": {"buffer": 10},
                }
            ),
            {
                "datasetName": "esa_landcover",
                "extractTypes": ["mean"],
                "resources": ["esa_lc_2020"],
                "kwargs": {"buffer": 10},
            },
        )

    def test_omitted_fields_become_the_web_defaults(self):
        self.assertEqual(
            _to_web_spec({"name": "ds"}),
            {"datasetName": "ds", "extractTypes": [], "resources": [], "kwargs": None},
        )

    def test_a_spec_with_no_name_is_an_actionable_error(self):
        with self.assertRaises(SelectionError) as ctx:
            _to_web_spec({"extract_types": ["mean"]})

        self.assertIn("esa_landcover", str(ctx.exception))


class PreviewRequestTests(TestCase):
    def setUp(self):
        self.world = World()

    def preview(self, **kwargs):
        kwargs.setdefault("boundary", self.world.fc.name)
        kwargs.setdefault("datasets", [{"name": "esa_landcover"}])
        return _preview_request(None, **kwargs)

    def test_counts_features_times_resources_times_extract_types(self):
        payload = self.preview()

        self.assertEqual(payload["feature_count"], 2)
        self.assertEqual(payload["task_count"], 2 * 2 * 2)

    def test_creates_nothing(self):
        self.preview()

        self.assertEqual(ExtractTask.objects.count(), 0)
        self.assertEqual(Request.objects.count(), 0)

    def test_already_processed_reflects_completed_tasks(self):
        self.assertEqual(self.preview()["already_processed"], 0.0)

        self.world.fill()

        payload = self.preview(datasets=[{"name": "esa_landcover", "extract_types": ["mean"]}])
        # 3 of the 4 (feature x year) mean extracts are done.
        self.assertEqual(payload["already_processed"], 0.75)

    def test_extract_types_narrow_the_plan(self):
        payload = self.preview(
            datasets=[{"name": "esa_landcover", "extract_types": ["mean"]}]
        )

        self.assertEqual(payload["task_count"], 4)
        self.assertEqual(payload["datasets"][0]["extract_types"], ["mean"])

    def test_feature_ids_narrow_the_plan(self):
        payload = self.preview(feature_ids=[self.world.features[0].id])

        self.assertEqual(payload["feature_count"], 1)
        self.assertEqual(payload["task_count"], 4)

    def test_feature_ids_from_another_boundary_are_rejected(self):
        with self.assertRaises(SelectionError) as ctx:
            self.preview(feature_ids=[999_999])

        self.assertIn("get_boundary", str(ctx.exception))

    def test_unknown_dataset_becomes_a_warning_not_a_failure(self):
        payload = self.preview(
            datasets=[{"name": "esa_landcover"}, {"name": "nope"}]
        )

        self.assertEqual(payload["warnings"], ["Dataset 'nope' not found or not available."])
        self.assertEqual(len(payload["datasets"]), 1)

    def test_unknown_boundary_points_at_search_boundaries(self):
        with self.assertRaises(SelectionError) as ctx:
            self.preview(boundary="nope")

        self.assertIn("search_boundaries", str(ctx.exception))

    @override_settings(MCP_SUBMIT_MAX_TASKS=3)
    def test_over_the_task_limit_is_flagged(self):
        self.assertTrue(self.preview()["over_limit"])

    def test_carries_attribution_for_what_would_be_extracted(self):
        payload = self.preview()

        self.assertIn("ESA Land Cover", payload["attribution"]["text"])
        self.assertIn("geoBoundaries", payload["attribution"]["text"])


class PlanHashTests(TestCase):
    def test_same_arguments_hash_the_same_regardless_of_feature_order(self):
        specs = [{"datasetName": "ds"}]

        self.assertEqual(
            _plan_hash("fc", specs, [3, 1, 2]), _plan_hash("fc", specs, [1, 2, 3])
        )

    def test_changing_the_datasets_changes_the_hash(self):
        self.assertNotEqual(
            _plan_hash("fc", [{"datasetName": "a"}], [1]),
            _plan_hash("fc", [{"datasetName": "b"}], [1]),
        )

    def test_changing_the_boundary_changes_the_hash(self):
        specs = [{"datasetName": "ds"}]

        self.assertNotEqual(_plan_hash("a", specs, [1]), _plan_hash("b", specs, [1]))


class AcceptedTests(TestCase):
    """Only an unambiguous yes counts as consent."""

    class Answer:
        def __init__(self, action, content=None):
            self.action = action
            self.content = content

    def test_accept_with_the_box_ticked(self):
        self.assertTrue(_accepted(self.Answer("accept", {"confirm": True})))

    def test_accept_with_the_box_unticked_is_not_consent(self):
        self.assertFalse(_accepted(self.Answer("accept", {"confirm": False})))

    def test_accept_with_no_content_is_not_consent(self):
        self.assertFalse(_accepted(self.Answer("accept")))

    def test_decline_and_cancel_are_not_consent(self):
        self.assertFalse(_accepted(self.Answer("decline", {"confirm": True})))
        self.assertFalse(_accepted(self.Answer("cancel")))

    def test_a_missing_answer_is_not_consent(self):
        self.assertFalse(_accepted(None))


class FakeContext:
    """Stands in for the FastMCP Context across a confirmation round trip."""

    def __init__(self, responses=None, state=None, supports_elicitation=True):
        self.input_responses = responses
        self.request_state = state
        self._supports = supports_elicitation

    class _Session:
        def __init__(self, supports):
            self._supports = supports

        def check_client_capability(self, _capabilities):
            return self._supports

    @property
    def session(self):
        return self._Session(self._supports)


class Answer:
    def __init__(self, action="accept", content=None):
        self.action = action
        self.content = content


class SubmitRequestTests(TestCase):
    """Exercises the registered tool, because the consent gate lives there."""

    def setUp(self):
        self.world = World()
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        EmailAddress.objects.create(
            user=self.user, email="u@example.com", verified=True, primary=True
        )
        self.submit = _registered_tool("submit_request", lambda: self.user)

    def call(self, ctx=None, **kwargs):
        kwargs.setdefault("boundary", self.world.fc.name)
        kwargs.setdefault(
            "datasets", [{"name": "esa_landcover", "extract_types": ["mean"]}]
        )
        kwargs.setdefault("name", "My export")
        return self.submit(ctx=ctx or FakeContext(), user=self.user, **kwargs)

    def test_first_call_asks_the_user_and_creates_nothing(self):
        result = self.call()

        self.assertEqual(Request.objects.count(), 0)
        self.assertEqual(ExtractTask.objects.count(), 0)
        input_required = result.input_required
        self.assertIn("confirm", input_required.input_requests)
        message = input_required.input_requests["confirm"].params.message
        self.assertIn("Testland ADM1", message)
        self.assertIn("4 extractions", message)

    def test_confirmed_call_creates_the_request_with_source_mcp(self):
        first = self.call()
        state = first.input_required.request_state

        with mock.patch("analytics.signals.chain"):
            result = self.call(
                ctx=FakeContext(
                    responses={"confirm": Answer(content={"confirm": True})}, state=state
                )
            )

        request = Request.objects.get()
        self.assertEqual(request.source, "mcp")
        self.assertEqual(request.contact, "u@example.com")
        self.assertEqual(request.user, self.user)
        self.assertEqual(request.custom_name, "My export")
        self.assertEqual(result.structured_content["task_count"], 4)
        self.assertEqual(ExtractTask.objects.count(), 4)

    def test_declining_creates_nothing(self):
        with mock.patch("analytics.signals.chain"):
            result = self.call(
                ctx=FakeContext(responses={"confirm": Answer(action="decline")})
            )

        self.assertEqual(Request.objects.count(), 0)
        self.assertTrue(result.structured_content["cancelled"])

    def test_arguments_changed_after_consent_are_rejected(self):
        first = self.call()
        state = first.input_required.request_state

        with self.assertRaises(Exception) as ctx:
            self.call(
                name="Different",
                datasets=[{"name": "esa_landcover", "extract_types": ["count"]}],
                ctx=FakeContext(
                    responses={"confirm": Answer(content={"confirm": True})}, state=state
                ),
            )

        self.assertIn("re-confirm", str(ctx.exception))
        self.assertEqual(Request.objects.count(), 0)

    def test_client_without_elicitation_is_told_to_ask_the_user_itself(self):
        result = self.call(ctx=FakeContext(supports_elicitation=False))

        self.assertEqual(Request.objects.count(), 0)
        text = result.content[0].text
        self.assertIn("confirm=true", text)
        self.assertIn("4 extractions", text)

    def test_explicit_confirm_true_submits_without_elicitation(self):
        with mock.patch("analytics.signals.chain"):
            self.call(ctx=FakeContext(supports_elicitation=False), confirm=True)

        self.assertEqual(Request.objects.count(), 1)

    @override_settings(MCP_SUBMIT_MAX_TASKS=2)
    def test_over_the_limit_refuses_before_asking(self):
        with self.assertRaises(Exception) as ctx:
            self.call()

        self.assertIn("limit", str(ctx.exception))
        self.assertEqual(Request.objects.count(), 0)

    def test_nothing_resolvable_refuses_before_asking(self):
        with self.assertRaises(Exception) as ctx:
            self.call(datasets=[{"name": "nope"}])

        self.assertIn("Nothing to extract", str(ctx.exception))
        self.assertEqual(Request.objects.count(), 0)

    def test_anonymous_callers_cannot_export(self):
        submit = _registered_tool("submit_request", lambda: None)

        with self.assertRaises(Exception) as ctx:
            submit(
                boundary=self.world.fc.name,
                datasets=[{"name": "esa_landcover"}],
                name="x",
                ctx=FakeContext(),
                user=None,
            )

        self.assertIn("signed-in", str(ctx.exception))


class RequestStatusTests(TestCase):
    def setUp(self):
        self.world = World().fill()

    def test_reports_progress_and_links_for_a_finished_export(self):
        request = self.world.make_request()

        payload = _get_request_status(None, str(request.id))

        self.assertEqual(payload["status_label"], "completed")
        self.assertEqual(payload["tasks_completed"], 3)
        self.assertEqual(payload["tasks_total"], 3)
        self.assertEqual(payload["progress"], 1.0)
        self.assertIn(str(request.id), payload["download_url"])
        self.assertIn(str(request.id), payload["documentation_url"])
        self.assertIn(str(request.id), payload["visualization_url"])

    def test_an_unfinished_export_has_no_links(self):
        request = self.world.make_request(status=0)

        payload = _get_request_status(None, str(request.id))

        self.assertEqual(payload["status_label"], "processing")
        self.assertNotIn("download_url", payload)

    def test_carries_attribution_for_what_the_export_used(self):
        request = self.world.make_request()

        payload = _get_request_status(None, str(request.id))

        self.assertIn("ESA Land Cover", payload["attribution"]["text"])

    def test_a_malformed_id_is_an_actionable_error_not_a_crash(self):
        with self.assertRaises(SelectionError) as ctx:
            _get_request_status(None, "not-a-uuid")

        self.assertIn("list_my_requests", str(ctx.exception))


class ListMyRequestsTests(TestCase):
    def setUp(self):
        self.world = World().fill()
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        EmailAddress.objects.create(
            user=self.user, email="u@example.com", verified=True, primary=True
        )
        self.mine = self.world.make_request(user=self.user)
        self.by_email = self.world.make_request(contact="U@EXAMPLE.COM")
        self.other = self.world.make_request(contact="someone@else.test")

    def test_lists_owned_and_email_matched_exports(self):
        payload = _list_my_requests(self.user)

        ids = {r["request_id"] for r in payload["requests"]}
        self.assertEqual(ids, {str(self.mine.id), str(self.by_email.id)})

    def test_status_filter(self):
        Request.objects.filter(pk=self.mine.pk).update(status=0)

        payload = _list_my_requests(self.user, status=0)

        self.assertEqual(
            [r["request_id"] for r in payload["requests"]], [str(self.mine.id)]
        )

    def test_paging_reports_the_total(self):
        payload = _list_my_requests(self.user, limit=1)

        self.assertEqual(len(payload["requests"]), 1)
        self.assertEqual(payload["total"], 2)
        self.assertTrue(payload["truncated"])

    def test_anonymous_callers_have_no_exports_to_list(self):
        from mcp_server.auth import AuthenticationRequired

        with self.assertRaises(AuthenticationRequired):
            _list_my_requests(None)


def _registered_tool(name: str, user_resolver):
    """The undecorated function body of a registered tool.

    submit_request's guard lives in the registered wrapper, not in a `_name`
    helper, so these tests reach it through the server's tool registry rather
    than duplicating the logic.
    """
    import asyncio

    from mcp_server.server import build_server

    mcp = build_server(auth=None, user_resolver=user_resolver)
    return asyncio.run(mcp.get_tool(name)).fn
