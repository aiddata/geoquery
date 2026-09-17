"""analytics.services — the submission rules, independent of HTTP.

RequestViewStandardSubmissionTest (test_views.py) already pins the web API's
side of this; these tests pin the parts the MCP server depends on directly:
that planning writes nothing, that warnings keep their exact wording, that
`source` is recorded, and that `requests_for_user` agrees with the account
history endpoint.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from allauth.account.models import EmailAddress

from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from analytics.services import (
    NoExtractTasksError,
    create_request,
    request_links,
    request_progress,
    requests_for_user,
    resolve_request_plan,
)
from catalog.models import Catalog
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from guardian.shortcuts import assign_perm

User = get_user_model()


class SubmissionFixture(TestCase):
    """One dataset with two resources and two options, over two features."""

    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="ds", path="/data/rasters/ds", type="raster", active=True, public=True
        )
        self.resources = [
            DatasetResource.objects.create(
                dataset=self.dataset, name=f"ds_{year}", path=f"{year}.tif", label=str(year)
            )
            for year in (2019, 2020)
        ]
        self.pos = [
            ProcessingOption.objects.create(
                dataset=self.dataset,
                short_name=short_name,
                function=f"f_{short_name}",
                active=True,
                public=True,
            )
            for short_name in ("mean", "sum")
        ]
        self.fc = FeatureCollection.objects.create(
            name="fc", path="/data/boundaries/fc.gpkg", active=True, public=True
        )
        self.features = [Feature.objects.create(shape="POINT(0 0)") for _ in range(2)]
        self.fms = [
            FeatMap.objects.create(fc=self.fc, geom=f) for f in self.features
        ]
        self.feature_ids = [f.id for f in self.features]

    def spec(self, **overrides):
        return {"datasetName": self.dataset.name, **overrides}


class ResolveRequestPlanTests(SubmissionFixture):
    def test_task_count_is_features_times_resources_times_options(self):
        plan = resolve_request_plan(None, self.feature_ids, [self.spec()])

        self.assertEqual(plan.task_count, 2 * 2 * 2)
        self.assertEqual(plan.warnings, [])

    def test_planning_creates_nothing(self):
        resolve_request_plan(None, self.feature_ids, [self.spec()])

        self.assertEqual(ExtractTask.objects.count(), 0)
        self.assertEqual(Request.objects.count(), 0)

    def test_extract_types_and_resources_narrow_the_plan(self):
        plan = resolve_request_plan(
            None,
            self.feature_ids,
            [self.spec(extractTypes=["mean"], resources=["ds_2020"])],
        )

        self.assertEqual(plan.task_count, 2)

    def test_unknown_dataset_is_skipped_with_the_exact_warning(self):
        plan = resolve_request_plan(
            None, self.feature_ids, [{"datasetName": "nope"}, self.spec()]
        )

        self.assertEqual(
            plan.warnings, ["Dataset 'nope' not found or not available."]
        )
        self.assertEqual(len(plan.resolved), 1)

    def test_missing_dataset_name_is_skipped_with_the_exact_warning(self):
        spec = {"extractTypes": ["mean"]}

        plan = resolve_request_plan(None, self.feature_ids, [spec])

        self.assertEqual(
            plan.warnings, [f"Skipped dataset missing datasetName: {spec}"]
        )

    def test_nothing_resolvable_warns_once_naming_the_dataset(self):
        plan = resolve_request_plan(
            None, self.feature_ids, [self.spec(extractTypes=["absent"])]
        )

        self.assertEqual(
            plan.warnings,
            ["No processing options, resources, or features found for dataset 'ds'."],
        )

    def test_warnings_keep_submission_order(self):
        plan = resolve_request_plan(
            None,
            self.feature_ids,
            [{"datasetName": "a"}, self.spec(), {"datasetName": "b"}],
        )

        self.assertEqual(
            plan.warnings,
            [
                "Dataset 'a' not found or not available.",
                "Dataset 'b' not found or not available.",
            ],
        )

    def test_private_dataset_is_invisible_without_a_grant(self):
        Dataset.objects.filter(pk=self.dataset.pk).update(public=False)

        plan = resolve_request_plan(None, self.feature_ids, [self.spec()])

        self.assertEqual(plan.resolved, [])

    def test_catalog_grant_makes_a_private_dataset_resolvable(self):
        Dataset.objects.filter(pk=self.dataset.pk).update(public=False)
        user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        catalog = Catalog.objects.create(name="c")
        catalog.datasets.add(self.dataset)
        assign_perm("catalog.access_catalog", user, catalog)

        plan = resolve_request_plan(user, self.feature_ids, [self.spec()])

        self.assertEqual(len(plan.resolved), 1)

    def test_features_in_an_invisible_collection_produce_no_tasks(self):
        FeatureCollection.objects.filter(pk=self.fc.pk).update(public=False)

        plan = resolve_request_plan(None, self.feature_ids, [self.spec()])

        self.assertEqual(plan.resolved, [])


class CreateRequestTests(SubmissionFixture):
    def create(self, **overrides):
        kwargs = dict(
            user=None,
            contact="a@example.com",
            name="My export",
            feature_ids=self.feature_ids,
            datasets=[self.spec()],
        )
        kwargs.update(overrides)
        return create_request(**kwargs)

    def test_creates_one_task_per_triple_and_one_request_map_row_each(self):
        created = self.create()

        self.assertEqual(created.task_count, 8)
        self.assertEqual(ExtractTask.objects.count(), 8)
        self.assertEqual(RequestMap.objects.filter(request=created.request).count(), 8)

    def test_request_map_rows_carry_the_dataset_id(self):
        created = self.create()

        dataset_ids = set(
            RequestMap.objects.filter(request=created.request).values_list(
                "dataset_id", flat=True
            )
        )
        self.assertEqual(dataset_ids, {self.dataset.id})

    def test_request_starts_queued_with_the_submitted_selection_recorded(self):
        created = self.create(selection_label="Ghana", selection_detail="ADM2")

        req = created.request
        self.assertEqual(req.status, -1)
        self.assertEqual(req.data["selection_label"], "Ghana")
        self.assertEqual(req.data["selection_detail"], "ADM2")
        self.assertEqual(req.data["feature_ids"], self.feature_ids)
        self.assertEqual(req.data["datasets"][0]["dataset_name"], "ds")

    def test_source_defaults_to_web_and_is_overridable(self):
        self.assertEqual(self.create().request.source, "web")
        self.assertEqual(self.create(source="mcp").request.source, "mcp")

    def test_resubmission_reuses_tasks_and_bumps_deprioritized_ones(self):
        self.create()
        ExtractTask.objects.update(priority=0)

        second = self.create()

        self.assertEqual(ExtractTask.objects.count(), 8)
        self.assertEqual(second.task_count, 8)
        self.assertEqual(
            set(ExtractTask.objects.values_list("priority", flat=True)), {1}
        )

    def test_already_high_priority_task_is_not_rewritten(self):
        self.create()
        ExtractTask.objects.update(priority=5)

        self.create()

        self.assertEqual(
            set(ExtractTask.objects.values_list("priority", flat=True)), {5}
        )

    def test_bulk_priority_bump_prunes_to_one_partition(self):
        """extract_tasks is LIST partitioned on dataset_id. An UPDATE that
        filters by id alone doesn't get the same partition-constraint
        propagation a SELECT does -- Postgres falls back to scanning every
        partition instead of pruning to the owning one (confirmed against
        production: 4.1s unpruned vs 0.2ms pruned for an equivalent single-row
        update). dataset_id must always ride along on this statement's WHERE
        clause, redundant with id or not, to get the fast plan.
        """
        self.create()
        ExtractTask.objects.update(priority=0)

        with CaptureQueriesContext(connection) as ctx:
            self.create()

        bump_queries = [
            q["sql"] for q in ctx.captured_queries
            if "UPDATE" in q["sql"] and "extract_tasks" in q["sql"] and "priority" in q["sql"]
        ]
        self.assertTrue(bump_queries, "expected at least one priority-bump UPDATE")
        for sql in bump_queries:
            self.assertIn(
                f"\"dataset_id\" = {self.dataset.id}", sql,
                f"priority-bump UPDATE missing dataset_id, can't be partition-pruned: {sql}",
            )

    def test_fallback_priority_bump_on_first_create_prunes_to_one_partition(self):
        """Same partition-pruning requirement as the bulk bump above, but for
        the per-task fallback path (_build_tasks' else branch): every task
        created on demand here defaults to priority=0, so this fires on
        every single task of a first-time submission -- the hot path behind
        the production incident this closes (a "fairly small" request still
        took minutes, one unpruned ~seconds-each UPDATE per task, all inside
        one long transaction that ended up blocking other submissions too).
        """
        with CaptureQueriesContext(connection) as ctx:
            self.create()

        bump_queries = [
            q["sql"] for q in ctx.captured_queries
            if "UPDATE" in q["sql"] and "extract_tasks" in q["sql"] and "priority" in q["sql"]
        ]
        self.assertTrue(bump_queries, "expected at least one priority-bump UPDATE")
        for sql in bump_queries:
            self.assertIn(
                f"\"dataset_id\" = {self.dataset.id}", sql,
                f"priority-bump UPDATE missing dataset_id, can't be partition-pruned: {sql}",
            )

    def test_nothing_resolvable_raises_with_the_warnings_attached(self):
        with self.assertRaises(NoExtractTasksError) as ctx:
            self.create(datasets=[{"datasetName": "nope"}])

        self.assertEqual(
            ctx.exception.warnings, ["Dataset 'nope' not found or not available."]
        )
        self.assertEqual(Request.objects.count(), 0)

    def test_response_dict_omits_warnings_when_there_are_none(self):
        self.assertNotIn("warnings", self.create().as_response_dict())

    def test_response_dict_includes_warnings_when_a_dataset_was_skipped(self):
        created = self.create(datasets=[self.spec(), {"datasetName": "nope"}])

        self.assertEqual(
            created.as_response_dict()["warnings"],
            ["Dataset 'nope' not found or not available."],
        )

    def test_response_dict_labels_the_status(self):
        data = self.create().as_response_dict()

        self.assertEqual(data["status"], -1)
        self.assertEqual(data["status_label"], "queued")


class RequestProgressAndLinksTests(SubmissionFixture):
    def setUp(self):
        super().setUp()
        self.created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=self.feature_ids,
            datasets=[self.spec(extractTypes=["mean"], resources=["ds_2020"])],
        )

    def test_progress_counts_completed_over_total(self):
        self.assertEqual(request_progress(self.created.request), (0, 2))

        task = ExtractTask.objects.first()
        ExtractTask.objects.filter(pk=task.pk).update(status=1)

        self.assertEqual(request_progress(self.created.request), (1, 2))

    def test_progress_does_not_bump_priorities(self):
        ExtractTask.objects.update(priority=0)

        request_progress(self.created.request)

        self.assertEqual(
            set(ExtractTask.objects.values_list("priority", flat=True)), {0}
        )

    def test_incomplete_request_has_no_links(self):
        self.assertEqual(request_links(self.created.request), {})

    def test_completed_request_links_to_download_docs_and_viz(self):
        req = self.created.request
        Request.objects.filter(pk=req.pk).update(status=1)
        req.refresh_from_db()

        links = request_links(req)

        self.assertEqual(links["download_url"], f"http://localhost:8000/requests/{req.id}/{req.id}.zip")
        self.assertEqual(
            links["documentation_url"],
            f"http://localhost:8000/requests/{req.id}/{req.id}_documentation.html",
        )
        self.assertEqual(links["visualization_url"], f"http://localhost:5173/viz/{req.id}")


class RequestsForUserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="x"
        )
        EmailAddress.objects.create(
            user=self.user, email="u@example.com", verified=True, primary=True
        )
        EmailAddress.objects.create(
            user=self.user, email="old@example.com", verified=True
        )
        self.owned = Request.objects.create(contact="u@example.com", user=self.user)
        self.by_email = Request.objects.create(contact="OLD@example.com")
        self.unverified = Request.objects.create(contact="other@example.com")
        Request.objects.create(contact="someone@else.test")

    def test_includes_fk_owned_and_verified_email_matches(self):
        ids = set(requests_for_user(self.user).values_list("id", flat=True))

        self.assertEqual(ids, {self.owned.id, self.by_email.id})

    def test_matches_the_account_history_endpoint(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("my-requests"))

        self.assertEqual(
            [r["id"] for r in response.json()],
            [str(r.id) for r in requests_for_user(self.user)],
        )
