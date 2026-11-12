from datetime import datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from datasets.docs.text import (
    DESCRIPTION_LIMIT,
    absolute_url,
    cell,
    date_range,
    front_matter,
    join_words,
    license_text,
    link,
    meta_description,
    slug,
    year_range,
)


def dt(year, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


class SlugTests(SimpleTestCase):
    def test_lowercases_and_hyphenates(self):
        self.assertEqual(slug("gB_57dcd43_NPL_ADM1"), "gb-57dcd43-npl-adm1")
        self.assertEqual(slug("TIGER"), "tiger")

    def test_empty(self):
        self.assertEqual(slug("__"), "")
        self.assertEqual(slug(None), "")


class CellTests(SimpleTestCase):
    def test_one_line_with_pipes_escaped(self):
        self.assertEqual(cell("a |\n b"), "a \\| b")

    def test_dash_when_empty(self):
        self.assertEqual(cell(None), "—")


class UrlTests(SimpleTestCase):
    def test_scheme_is_added_when_missing(self):
        self.assertEqual(absolute_url("www.geoboundaries.org"), "https://www.geoboundaries.org")
        self.assertEqual(absolute_url("http://x.org"), "http://x.org")
        self.assertEqual(absolute_url(None), "")


class RangeTests(SimpleTestCase):
    def test_year_range(self):
        self.assertEqual(year_range(dt(2000), dt(2020)), "2000–2020")
        self.assertEqual(year_range(dt(2015), dt(2015, 12)), "2015")
        self.assertEqual(year_range(None, None), "—")

    def test_date_range(self):
        self.assertEqual(date_range(dt(2000), None), "2000-01-01 – —")


class JoinWordsTests(SimpleTestCase):
    def test_joins_with_and(self):
        self.assertEqual(join_words(["a"]), "a")
        self.assertEqual(join_words(["a", "b", "c"]), "a, b and c")


class MetaDescriptionTests(SimpleTestCase):
    def test_lead_detail_and_suffix_are_joined(self):
        self.assertEqual(meta_description("Malaria.", "Cases.", " More."), "Malaria. Cases. More.")

    def test_detail_that_does_not_fit_falls_back_to_its_first_sentence(self):
        detail = "Short first sentence. " + "Word " * 40
        self.assertEqual(meta_description("Lead.", detail), "Lead. Short first sentence.")

    def test_detail_is_dropped_rather_than_cut(self):
        self.assertEqual(meta_description("Lead.", "word " * 40 + ".", " Suffix."), "Lead. Suffix.")

    def test_overlong_lead_is_cut_at_a_word(self):
        result = meta_description("word " * 100, "Detail.", " Suffix.")
        self.assertLessEqual(len(result), DESCRIPTION_LIMIT)
        self.assertTrue(result.endswith("word… Suffix."))


class FrontMatterTests(SimpleTestCase):
    def test_description_is_quoted(self):
        self.assertEqual(
            front_matter('Rain: "monthly" #1'),
            '---\ndescription: "Rain: \\"monthly\\" #1"\n---\n\n',
        )


class AbbreviationTests(SimpleTestCase):
    def test_first_sentence_is_not_split_at_an_abbreviation(self):
        detail = "The U.S. Census Bureau publishes county boundaries. " + "Word " * 40
        self.assertIn(
            "The U.S. Census Bureau publishes county boundaries.", meta_description("Lead.", detail)
        )


class LinkTests(SimpleTestCase):
    def test_bare_label_without_url(self):
        self.assertEqual(link("Label", None), "Label")

    def test_scheme_is_added(self):
        self.assertEqual(link("Label", "x.org/a"), "[Label](https://x.org/a)")


class LicenseTextTests(SimpleTestCase):
    def test_not_recorded(self):
        obj = SimpleNamespace(license="", license_url="")
        self.assertEqual(license_text(obj), "Not recorded — see the source link")

    def test_license_with_url_is_a_link(self):
        obj = SimpleNamespace(license="CC BY 4.0", license_url="x.org/l")
        self.assertEqual(license_text(obj), "[CC BY 4.0](https://x.org/l)")

    def test_license_without_url_is_plain(self):
        obj = SimpleNamespace(license="CC BY 4.0", license_url=None)
        self.assertEqual(license_text(obj), "CC BY 4.0")
