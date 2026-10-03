from unittest import mock

from django.test import TestCase

from analytics.models import Request


class RequestDispatchSignalTests(TestCase):
    def test_creating_at_status_minus1_schedules_the_completion_sweep(self):
        with (
            mock.patch("analytics.tasks.maintenance.process_user_requests.delay") as mock_sweep,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=-1, data={})

        mock_sweep.assert_called_once_with()

    def test_creating_at_status_0_schedules_the_completion_sweep(self):
        with (
            mock.patch("analytics.tasks.maintenance.process_user_requests.delay") as mock_sweep,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=0, data={})

        mock_sweep.assert_called_once_with()

    def test_creating_at_status_3_does_not_schedule_the_completion_sweep(self):
        with (
            mock.patch("analytics.tasks.maintenance.process_user_requests.delay") as mock_sweep,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=3, data={})

        mock_sweep.assert_not_called()

    def test_creating_at_status_4_does_not_schedule_the_completion_sweep_directly(self):
        with (
            mock.patch("analytics.tasks.maintenance.process_user_requests.delay") as mock_sweep,
            mock.patch(
                "analytics.tasks.requests.materialize_request_tasks.delay"
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=4, data={})

        mock_sweep.assert_not_called()

    def test_creating_at_status_4_schedules_materialization(self):
        with (
            mock.patch(
                "analytics.tasks.requests.materialize_request_tasks.delay"
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            req = Request.objects.create(contact="a@example.com", status=4, data={})

        mock_delay.assert_called_once_with(str(req.id))

    def test_creating_at_status_3_does_not_schedule_materialization(self):
        with (
            mock.patch(
                "analytics.tasks.requests.materialize_request_tasks.delay"
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Request.objects.create(contact="a@example.com", status=3, data={})

        mock_delay.assert_not_called()
