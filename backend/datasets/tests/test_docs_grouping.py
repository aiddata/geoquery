from datetime import datetime, timezone

from django.test import SimpleTestCase

from datasets.docs.grouping import (
    GroupingError,
    build_pages,
    gb_version,
    level_label,
    page_key,
)
from features.models import FeatureCollection


def fc(name, group_name=None, level=None, added=2026, title=None, source="geoBoundaries",
       group_title=None):
    return FeatureCollection(
        name=name, group_name=group_name, group_level=level, title=title or name,
        source_name=source, group_title=group_title,
        date_added=datetime(added, 1, 1, tzinfo=timezone.utc),
    )


class PageKeyTests(SimpleTestCase):
    def test_geoboundaries_drops_the_release(self):
        self.assertEqual(page_key(fc("gB_57dcd43_NPL_ADM1", "gb_v6_npl")), "gb_npl")
        self.assertEqual(page_key(fc("gB_x_NPL_ADM1", "GB_V7_NPL")), "gb_npl")

    def test_other_groups_keep_their_name(self):
        self.assertEqual(page_key(fc("TIGER_2025_COUNTY", "TIGER")), "TIGER")
        self.assertEqual(page_key(fc("gb_custom_thing", "gb_custom")), "gb_custom")

    def test_ungrouped_collection_uses_its_own_name(self):
        self.assertEqual(page_key(fc("lonely")), "lonely")


class BuildPagesTests(SimpleTestCase):
    def test_every_release_of_a_country_shares_one_page(self):
        pages = build_pages([
            fc("gB_57dcd43_NPL_ADM1", "gb_v6_npl", 1, added=2026),
            fc("gB_old_NPL_ADM1", "gb_v5_npl", 1, added=2024),
            fc("gB_57dcd43_NPL_ADM0", "gb_v6_npl", 0, added=2026),
        ])
        self.assertEqual([p.slug for p in pages], ["gb-npl"])
        self.assertEqual(
            [c.name for c in pages[0].collections],
            ["gB_57dcd43_NPL_ADM0", "gB_57dcd43_NPL_ADM1", "gB_old_NPL_ADM1"],
        )

    def test_keys_that_slugify_the_same_share_a_page(self):
        pages = build_pages([
            fc("a", "TIGER", source="US Census"),
            fc("b", "tiger", source="US Census"),
        ])
        self.assertEqual([p.slug for p in pages], ["tiger"])

    def test_a_page_mixing_sources_is_an_error(self):
        with self.assertRaisesRegex(GroupingError, "boundaries/tiger/"):
            build_pages([fc("a", "TIGER", source="US Census"), fc("b", "tiger", source="Other")])

    def test_an_empty_slug_is_an_error(self):
        with self.assertRaises(GroupingError):
            build_pages([fc("x", "__")])

    def test_a_slug_of_index_is_an_error(self):
        with self.assertRaisesRegex(GroupingError, "index"):
            build_pages([fc("x", "Index")])

    def test_collections_without_a_level_come_last(self):
        page = build_pages([fc("b", "g", None, source="s"), fc("a", "g", 2, source="s")])[0]
        self.assertEqual([c.name for c in page.collections], ["a", "b"])


class PageTitleTests(SimpleTestCase):
    def test_geoboundaries_page_is_named_after_the_country(self):
        page = build_pages([fc("gB_x_NPL_ADM0", "gb_v6_npl", 0, group_title="Nepal - GeoBoundaries v6")])[0]
        self.assertTrue(page.geoboundaries)
        self.assertEqual(page.place, "Nepal")
        self.assertEqual(page.title, "Nepal boundaries")

    def test_other_pages_use_the_group_title(self):
        page = build_pages([fc("a", "atlas", source="s", group_title="Atlas of Urban Expansion")])[0]
        self.assertFalse(page.geoboundaries)
        self.assertEqual(page.title, "Atlas of Urban Expansion")


class PlaceFallbackTests(SimpleTestCase):
    def test_geoboundaries_without_group_title_uses_iso3(self):
        page = build_pages([fc("gB_x_NPL_ADM0", "gb_v6_npl", 0)])[0]
        self.assertEqual(page.place, "NPL")


class PageOrderTests(SimpleTestCase):
    def test_title_ties_break_on_slug(self):
        pages = build_pages([
            fc("a", "zed", source="s", group_title="Same"),
            fc("b", "abc", source="s", group_title="Same"),
        ])
        self.assertEqual([p.slug for p in pages], ["abc", "zed"])


class LevelLabelTests(SimpleTestCase):
    def test_geoboundaries_label_uses_the_canonical_name(self):
        c = fc("gB_x_NPL_ADM1", "gb_v6_npl", 1, title="geoBoundaries v6 - Nepal ADM1 (Provinces)")
        self.assertEqual(level_label(c), "ADM1 (Provinces)")

    def test_other_levels_and_missing_levels(self):
        self.assertEqual(level_label(fc("a", "TIGER", 2)), "Level 2")
        self.assertEqual(level_label(fc("a", "atlas")), "")

    def test_sections_group_consecutive_levels(self):
        page = build_pages([
            fc("gB_a_NPL_ADM1", "gb_v6_npl", 1, title="X ADM1 (Provinces)", added=2026),
            fc("gB_b_NPL_ADM1", "gb_v5_npl", 1, title="X ADM1 (Province)", added=2024),
        ])[0]
        self.assertEqual([(h, len(m)) for h, m in page.sections()], [("ADM1 (Provinces)", 2)])

    def test_levelless_collections_each_get_a_section(self):
        page = build_pages([fc("a", "g", source="s"), fc("b", "g", source="s")])[0]
        self.assertEqual([(h, len(m)) for h, m in page.sections()], [("", 1), ("", 1)])


class VersionTests(SimpleTestCase):
    def test_version_comes_from_the_collection_name(self):
        self.assertEqual(gb_version(fc("gB_57dcd43_NPL_ADM1")), "57dcd43")
        self.assertIsNone(gb_version(fc("TIGER_2025_COUNTY")))
