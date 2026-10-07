"""BaseIngestCommand's post-ingest hook dispatch."""

from unittest import mock

from django.test import SimpleTestCase

from analytics.management.commands.base import BaseIngestCommand


class _NoopIngestCommand(BaseIngestCommand):
    """Minimal subclass: handle() does nothing but record that it ran."""

    def __init__(self, *args, skip=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._skip = skip
        self.ran = False

    def handle(self, *args, **options):
        self.ran = True
        if self._skip:
            self.skip_post_ingest_hooks = True


class PostIngestHookTests(SimpleTestCase):
    def test_dispatches_coverage_and_extract_by_default(self):
        cmd = _NoopIngestCommand()

        with mock.patch(
            "analytics.tasks.maintenance.trigger_coverage_and_extract"
        ) as task:
            cmd.execute(skip_checks=True, no_color=False, force_color=False)

        self.assertTrue(cmd.ran)
        task.delay.assert_called_once()

    def test_skips_dispatch_when_handle_sets_the_flag(self):
        cmd = _NoopIngestCommand(skip=True)

        with mock.patch(
            "analytics.tasks.maintenance.trigger_coverage_and_extract"
        ) as task:
            cmd.execute(skip_checks=True, no_color=False, force_color=False)

        self.assertTrue(cmd.ran)
        task.delay.assert_not_called()

    def test_flag_defaults_to_false(self):
        self.assertFalse(BaseIngestCommand.skip_post_ingest_hooks)
