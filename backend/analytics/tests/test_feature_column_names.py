"""Naming feature-dataset versions: the output column prefix of each spec."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from analytics.services import _unique_name, canonical_kwargs, clean_column_name, feature_column_names


class ColumnNameTests(SimpleTestCase):
    def test_spaces_become_underscores_and_other_characters_are_dropped(self):
        self.assertEqual(clean_column_name("  Battles 2020!"), "Battles_2020")
        self.assertEqual(clean_column_name("acled-v2 (fatal)"), "acledv2_fatal")
        self.assertEqual(clean_column_name("***"), "")

    def test_duplicates_get_a_numbered_suffix_ignoring_case(self):
        taken: set[str] = set()
        self.assertEqual(_unique_name("acled", taken), "acled")
        self.assertEqual(_unique_name("ACLED", taken), "ACLED_2")
        self.assertEqual(_unique_name("acled", taken), "acled_3")

    def test_request_names_are_keyed_by_dataset_and_kwargs(self):
        request = SimpleNamespace(data={"datasets": [
            {"dataset_id": 7, "kwargs": {"b": 1, "a": 2}, "name": "first"},
            {"dataset_id": 7, "kwargs": None, "name": None},  # a raster
            {"dataset_name": "old", "kwargs": {"a": 1}},  # made before names were stored
        ]})
        self.assertEqual(feature_column_names(request), {(7, canonical_kwargs({"a": 2, "b": 1})): "first"})
