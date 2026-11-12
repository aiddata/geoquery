from django.test import SimpleTestCase, TestCase

from datasets.models import Dataset
from datasets.tasks.create_docs import (
    DESCRIPTION_LIMIT,
    _build_dataset_page,
    meta_description,
    page_front_matter,
)


class MetaDescriptionTests(SimpleTestCase):
    def test_lead_detail_and_suffix_are_joined(self):
        self.assertEqual(meta_description("Malaria.", "Cases per person.", " More."), "Malaria. Cases per person. More.")

    def test_whitespace_is_collapsed(self):
        self.assertEqual(meta_description("  Two\n  lines  ", " a\n b "), "Two lines a b")

    def test_detail_that_does_not_fit_falls_back_to_its_first_sentence(self):
        detail = "Short first sentence. " + "word " * 40
        self.assertEqual(meta_description("Lead.", detail), "Lead. Short first sentence.")

    def test_detail_is_dropped_rather_than_cut(self):
        self.assertEqual(meta_description("Lead.", "word " * 40 + ".", " Suffix."), "Lead. Suffix.")

    def test_overlong_lead_is_cut_at_a_word_with_room_for_the_suffix(self):
        suffix = " Extract it with GeoQuery."
        result = meta_description("word " * 100, "Detail.", suffix)
        self.assertLessEqual(len(result), DESCRIPTION_LIMIT)
        self.assertTrue(result.endswith("word…" + suffix))


class PageFrontMatterTests(SimpleTestCase):
    def test_description_is_quoted_so_yaml_special_characters_are_safe(self):
        self.assertEqual(
            page_front_matter('Rain: "monthly" #1'),
            '---\ndescription: "Rain: \\"monthly\\" #1"\n---\n\n',
        )


class DatasetPageTests(TestCase):
    def test_page_starts_with_front_matter_from_the_description(self):
        ds = Dataset.objects.create(
            name="ds", path="/data/rasters/ds", type="raster",
            title="Malaria", description="Plasmodium falciparum incidence rate.",
        )
        page = _build_dataset_page(ds)
        self.assertTrue(
            page.startswith('---\ndescription: "Malaria. Plasmodium falciparum incidence rate. Free to extract')
        )
        self.assertIn("\n---\n\n# Malaria\n", page)

    def test_title_is_used_when_there_is_no_description(self):
        ds = Dataset.objects.create(name="ds", path="/data/rasters/ds", type="raster", title="Malaria")
        self.assertTrue(_build_dataset_page(ds).startswith('---\ndescription: "Malaria.'))
