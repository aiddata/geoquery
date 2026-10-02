"""manage_processing_task_errors — the retry cap, and the sweep that depends on it.

Before MAX_EXTRACT_TASK_ATTEMPTS existed this command reset every errored task
unconditionally and incremented `attempts` with nothing reading it, so a task
failing for a permanent reason cycled -1 -> 0 -> -1 once an hour forever.
Capping it is only safe because _check_request_tasks stops counting an
exhausted task as pending -- otherwise a request holding one would be
re-queued by the completion sweep indefinitely.
"""

from django.test import TestCase, override_settings

from analytics.management.commands.manage_processing_task_errors import (
    _manage_processing_task_errors,
)
from analytics.management.commands.manage_user_requests import _check_request_tasks
from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection


class ErrorSweepFixture(TestCase):
    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="ds", path="/data/ds", active=True, public=True
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
            public=True,
        )
        self.fc = FeatureCollection.objects.create(
            name="fc", path="/data/fc", active=True, public=True
        )
        self.feature = Feature.objects.create(shape="POINT(0 0)")
        self.fm = FeatMap.objects.create(fc=self.fc, geom=self.feature)

    def errored_task(self, attempts, resource=None):
        return ExtractTask.objects.create(
            dataset_id=self.dataset.id,
            resource_ids=[(resource or self.resource).id],
            fm=self.fm,
            po=self.po,
            status=-1,
            attempts=attempts,
        )


@override_settings(MAX_EXTRACT_TASK_ATTEMPTS=3)
class RetryCapTests(ErrorSweepFixture):
    def test_task_under_the_cap_is_returned_to_pending(self):
        task = self.errored_task(attempts=1)

        _manage_processing_task_errors(error_values=-1)

        task.refresh_from_db()
        self.assertEqual(task.status, 0)
        self.assertEqual(task.attempts, 2)

    def test_task_at_the_cap_is_left_alone(self):
        task = self.errored_task(attempts=3)

        _manage_processing_task_errors(error_values=-1)

        task.refresh_from_db()
        self.assertEqual(task.status, -1, "exhausted task should not be retried")
        self.assertEqual(task.attempts, 3, "attempts should not keep climbing")

    def test_repeated_sweeps_stop_at_the_cap(self):
        """The actual regression: an unbounded sweep cycles a poison task forever."""
        task = self.errored_task(attempts=0)

        for _ in range(10):
            _manage_processing_task_errors(error_values=-1)
            # Simulate the processor failing again each time it is retried.
            ExtractTask.objects.filter(id=task.id, dataset_id=task.dataset_id).update(
                status=-1
            )

        task.refresh_from_db()
        self.assertEqual(task.attempts, 3, "retries should have stopped at the cap")

    def test_dry_run_changes_nothing(self):
        task = self.errored_task(attempts=1)

        _manage_processing_task_errors(error_values=-1, dry_run=True)

        task.refresh_from_db()
        self.assertEqual(task.status, -1)
        self.assertEqual(task.attempts, 1)

    def test_explicit_max_attempts_overrides_the_setting(self):
        task = self.errored_task(attempts=3)

        _manage_processing_task_errors(error_values=-1, max_attempts=10)

        task.refresh_from_db()
        self.assertEqual(task.status, 0)


@override_settings(MAX_EXTRACT_TASK_ATTEMPTS=3)
class ExhaustedTaskDoesNotHangRequestTests(ErrorSweepFixture):
    """Why the cap and the completion sweep cannot ship separately.

    _check_request_tasks derives pending as total - completed, counting only
    status=1 as completed. An exhausted task is neither completed nor
    retryable, so without being counted as finished it would hold the request
    at pending forever -- the same shape as a stranded claim, but permanent.
    """

    def setUp(self):
        super().setUp()
        # A second resource so the two tasks differ on resource_ids: they share
        # dataset/fm/po, and the unique index keys on all four.
        self.resource2 = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r2", path="r2.tif"
        )
        self.request = Request.objects.create(status=-1, data={})
        self.done = ExtractTask.objects.create(
            dataset_id=self.dataset.id,
            resource_ids=[self.resource.id],
            fm=self.fm,
            po=self.po,
            status=1,
        )
        self.stuck = self.errored_task(attempts=3, resource=self.resource2)
        for task in (self.done, self.stuck):
            RequestMap.objects.create(
                request=self.request, task_id=task.id, dataset_id=task.dataset_id
            )

    def test_exhausted_task_is_not_counted_as_pending(self):
        pending, completed = _check_request_tasks(self.request, dry_run=True)

        self.assertEqual(pending, 0, "request should be able to finish")
        self.assertEqual(
            set(completed), {self.done.id},
            "the failed task must not appear as completed data",
        )

    def test_retryable_error_still_holds_the_request(self):
        """The cap must not make every error terminal -- only exhausted ones."""
        ExtractTask.objects.filter(
            id=self.stuck.id, dataset_id=self.stuck.dataset_id
        ).update(attempts=1)

        pending, completed = _check_request_tasks(self.request, dry_run=True)

        self.assertEqual(pending, 1, "a task with retries left is still pending")
        self.assertEqual(set(completed), {self.done.id})
