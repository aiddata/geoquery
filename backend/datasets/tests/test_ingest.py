"""Dataset ingest JSON → model field mapping."""

from django.test import SimpleTestCase

from datasets.ingest import _dataset_fields_from_json


class DatasetFieldsFromJsonTests(SimpleTestCase):
    def test_attribution_keys_are_kept(self):
        """license/license_url are Dataset fields, so ingest JSONs carrying
        them persist rather than being logged-and-dropped as unknown keys."""
        fields = _dataset_fields_from_json(
            {
                "name": "ds",
                "path": "/data/rasters/ds",
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "citation": "Author, A. (2020).",
                "source_name": "Agency",
                "source_url": "https://agency.test",
            }
        )

        self.assertEqual(fields["license"], "CC BY 4.0")
        self.assertEqual(
            fields["license_url"], "https://creativecommons.org/licenses/by/4.0/"
        )
        self.assertEqual(fields["citation"], "Author, A. (2020).")

    def test_unknown_keys_are_still_dropped(self):
        fields = _dataset_fields_from_json(
            {"name": "ds", "path": "/data/rasters/ds", "not_a_field": 1}
        )

        self.assertNotIn("not_a_field", fields)

    def test_mapped_is_derived_from_mappings(self):
        base = {"name": "ds", "path": "/data/rasters/ds"}

        self.assertFalse(_dataset_fields_from_json(base)["mapped"])
        self.assertTrue(
            _dataset_fields_from_json({**base, "mappings": {"a": 1}})["mapped"]
        )
