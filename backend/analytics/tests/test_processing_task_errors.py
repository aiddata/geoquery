"""manage_processing_task_errors — the retry cap, and the sweep that depends on it.

Before MAX_EXTRACT_TASK_ATTEMPTS existed this command reset every errored task
unconditionally and incremented `attempts` with nothing reading it, so a task
failing for a permanent reason cycled -1 -> 0 -> -1 once an hour forever.
Capping it also decides what happens to a request holding such a task: it is
marked failed (status -2) rather than either completing with silently missing
columns or being re-queued by the completion sweep forever.
"""

from django.test import TestCase, override_settings

from analytics.management.commands.manage_processing_task_errors import (
    _manage_processing_task_errors,
)
from analytics.management.commands.manage_user_requests import (
    _check_request_tasks,
    _manage_user_requests,
)
from analytics.models import ExtractTask, ProcessingOption, RequestMap
from analytics.services import create_request, materialize_request
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
class ExhaustedTaskFailsItsRequestTests(ErrorSweepFixture):
    """Why the cap and the completion sweep cannot ship separately.

    _check_request_tasks counts only status=1 as completed, so an exhausted
    task is neither completed nor retryable. Left in pending the sweep would
    requeue the request forever; quietly excluded, the request would complete
    and hand back a download missing that task's column. It is reported
    separately so the sweep can fail the request instead.

    Built through create_request/materialize_request rather than a hand-made
    Request: the sweep runs _validation_error first, and a Request with an
    empty data blob is itself one of the three validation failures, so a
    hand-made one gets marked -2 before reaching any of this.
    """

    def setUp(self):
        super().setUp()
        # Second resource so the request resolves to two tasks.
        self.resource2 = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r2", path="r2.tif"
        )
        created = create_request(
            user=None,
            contact="a@example.com",
            name=None,
            feature_ids=[self.feature.id],
            datasets=[{"datasetName": self.dataset.name}],
        )
        materialize_request(created.request)
        created.request.refresh_from_db()
        self.request = created.request

        task_ids = list(
            RequestMap.objects.filter(request=self.request).values_list(
                "task_id", flat=True
            )
        )
        self.assertEqual(len(task_ids), 2, "fixture should resolve to two tasks")
        self.done_id, self.stuck_id = task_ids
        ExtractTask.objects.filter(
            id=self.done_id, dataset_id=self.dataset.id
        ).update(status=1)
        ExtractTask.objects.filter(
            id=self.stuck_id, dataset_id=self.dataset.id
        ).update(status=-1, attempts=3)

    def _set_stuck_attempts(self, attempts):
        ExtractTask.objects.filter(
            id=self.stuck_id, dataset_id=self.dataset.id
        ).update(attempts=attempts)

    def test_exhausted_task_is_reported_separately(self):
        pending, completed, failed = _check_request_tasks(
            self.request, dry_run=True
        )

        self.assertEqual(failed, 1)
        self.assertEqual(
            set(completed), {self.done_id},
            "the failed task must not appear as completed data",
        )

    def test_retryable_error_is_not_reported_as_failed(self):
        """The cap must not make every error terminal -- only exhausted ones."""
        self._set_stuck_attempts(1)

        pending, completed, failed = _check_request_tasks(
            self.request, dry_run=True
        )

        self.assertEqual(failed, 0, "a task with retries left has not failed")
        self.assertEqual(pending, 1, "and is still pending")

    def test_sweep_marks_the_request_failed(self):
        """The contract: a request containing a dead task errors, it does not
        finish. Completing it would hand the user a download silently missing
        that task's column."""
        _manage_user_requests(request_id=str(self.request.id))

        self.request.refresh_from_db()
        self.assertEqual(
            self.request.status, -2,
            "request with a permanently failed task should be marked error",
        )
        self.assertIsNone(
            self.request.complete_time,
            "a failed request must not look completed",
        )

    def test_sweep_requeues_instead_of_failing_when_retries_remain(self):
        self._set_stuck_attempts(1)

        _manage_user_requests(request_id=str(self.request.id))

        self.request.refresh_from_db()
        self.assertNotEqual(
            self.request.status, -2,
            "a retryable error must not fail the request",
        )

    def test_dry_run_does_not_fail_the_request(self):
        _manage_user_requests(request_id=str(self.request.id), dry_run=True)

        self.request.refresh_from_db()
        self.assertEqual(
            self.request.status, -1, "dry run must not write status"
        )
