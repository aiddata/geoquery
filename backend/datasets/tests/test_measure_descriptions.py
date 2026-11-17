"""Measure labels in processing option descriptions, and updating them."""

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase

from analytics.models import ProcessingOption
from datasets.measures import measure_label, split_measure
from datasets.models import Dataset


class SplitMeasureTests(SimpleTestCase):
    def test_label_and_detail_are_split(self):
        self.assertEqual(
            split_measure("Minimum temperature {{{The lowest temperature, in degrees Celsius.}}}"),
            ("Minimum temperature", "The lowest temperature, in degrees Celsius."),
        )

    def test_plain_description_has_no_label(self):
        self.assertEqual(split_measure("average distance per unit of analysis"), (None, "average distance per unit of analysis"))
        self.assertEqual(split_measure(None), (None, ""))

    def test_label_falls_back_to_short_name(self):
        self.assertEqual(measure_label("mean", "Average slope {{{x}}}"), "Average slope")
        self.assertEqual(measure_label("mean", "average slope"), "mean")


class UpdateMeasureDescriptionsTests(TestCase):
    def setUp(self):
        self.ds = Dataset.objects.create(name="tmp", path="/d/tmp", active=True, public=True)
        self.po = ProcessingOption.objects.create(
            dataset=self.ds, short_name="min", function="rasterstats_default_min", description="minimum value", active=True
        )
        self.other = ProcessingOption.objects.create(
            dataset=self.ds, short_name="max", function="rasterstats_default_max", description="maximum value", active=True
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        doc = {
            "name": "tmp",
            "processing_options": [
                {"short_name": "min", "description": "Minimum temperature {{{The lowest temperature.}}}"},
                {"short_name": "max", "description": "maximum value"},  # unchanged
                {"short_name": "count", "description": "not in the database"},
            ],
        }
        Path(self.tmp.name, "tmp_ingest.json").write_text(json.dumps(doc))
        Path(self.tmp.name, "missing.json").write_text(json.dumps({"name": "nope", "processing_options": [{"short_name": "mean", "description": "x"}]}))

    def run_command(self, *args):
        out = StringIO()
        call_command("update_measure_descriptions", "--source", self.tmp.name, *args, stdout=out)
        return out.getvalue()

    def input_state(self):
        with connection.cursor() as c:
            c.execute("SELECT kind, object_id, generation FROM extract_input_state ORDER BY kind, object_id")
            return c.fetchall()

    def test_dry_run_changes_nothing(self):
        out = self.run_command("--dry-run")
        self.assertIn("1 description(s) would change", out)
        self.po.refresh_from_db()
        self.assertEqual(self.po.description, "minimum value")

    def test_only_the_changed_description_is_updated(self):
        out = self.run_command()
        self.assertIn("Updated 1 description(s)", out)
        self.assertIn("nope: not in this database", out)
        self.po.refresh_from_db(); self.other.refresh_from_db()
        self.assertEqual(self.po.description, "Minimum temperature {{{The lowest temperature.}}}")
        self.assertEqual(self.other.description, "maximum value")
        self.assertFalse(ProcessingOption.objects.filter(short_name="count").exists())

    def test_updating_descriptions_records_no_extract_input_change(self):
        before = self.input_state()
        self.run_command()
        self.assertEqual(self.input_state(), before)
