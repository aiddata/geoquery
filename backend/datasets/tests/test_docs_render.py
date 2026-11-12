import json
from datetime import datetime, timezone

from django.test import TestCase

from datasets.docs.coverage import FULL, PARTIAL
from datasets.docs.grouping import build_pages
from datasets.docs.text import DESCRIPTION_LIMIT, slug
from datasets.docs.render import (
    boundaries_index,
    boundary_page,
    dataset_page,
    datasets_index,
    redirect_html,
    topics,
)
from datasets.models import Dataset, DatasetResource, Mapping
from features.models import FeatureCollection

ADDED = datetime(2026, 8, 18, tzinfo=timezone.utc)


def make_dataset(name="malaria", **kw):
    kw.setdefault("title", "Malaria Incidence")
    kw.setdefault("description", "Plasmodium falciparum incidence rate.")
    return Dataset.objects.create(name=name, path=f"/{name}", type="raster", active=True, public=True, **kw)


def make_fc(name, level, **kw):
    kw.setdefault("group_name", "gb_v6_npl")
    kw.setdefault("group_title", "Nepal - GeoBoundaries v6")
    fc = FeatureCollection.objects.create(
        name=name, path=f"/{name}", group_level=level, source_name="geoBoundaries",
        source_url="https://www.geoboundaries.org", active=True, public=True,
        citation="Runfola, D. et al. (2020) geoBoundaries.", **kw,
    )
    FeatureCollection.objects.filter(id=fc.id).update(date_added=ADDED)
    fc.date_added = ADDED
    return fc


class DatasetPageTests(TestCase):
    def test_global_dataset(self):
        ds = make_dataset(is_global=True, citation="MAP (2026).", tags=["malaria", "health"])
        DatasetResource.objects.create(dataset=ds, name="malaria_2020", path="/x", label="2020",
                                       temporal=datetime(2020, 1, 1, tzinfo=timezone.utc))
        Mapping.objects.create(dataset=ds, map_val=1, map_name="Low")

        page = dataset_page(ds, [])

        self.assertTrue(page.startswith('---\ndescription: "Malaria Incidence. Plasmodium'))
        self.assertIn("# Malaria Incidence\n", page)
        self.assertIn("| License | Not recorded — see the source link |", page)
        self.assertIn("## Available for\n\nEvery boundary in GeoQuery.", page)
        self.assertIn("| malaria_2020 | 2020 | 2020-01-01 |", page)
        self.assertIn("| 1 | Low |", page)
        self.assertIn("## Citation\n\nMAP (2026).", page)

    def test_regional_dataset_lists_its_pages(self):
        ds = make_dataset(is_global=False)
        nepal = build_pages([make_fc("gB_57dcd43_NPL_ADM0", 0)])[0]
        page = dataset_page(ds, [(nepal, PARTIAL)])
        self.assertIn("| [Nepal boundaries](../boundaries/gb-npl.md) | Partial |", page)


class BoundaryPageTests(TestCase):
    def setUp(self):
        self.adm0 = make_fc("gB_57dcd43_NPL_ADM0", 0, title="geoBoundaries v6 - Nepal ADM0 (Country)")
        self.adm1 = make_fc("gB_57dcd43_NPL_ADM1", 1, title="geoBoundaries v6 - Nepal ADM1 (Provinces)")
        self.page = build_pages([self.adm0, self.adm1])[0]
        self.malaria = make_dataset(tags=["malaria"], is_global=True)
        self.pop = make_dataset("pop", title="Population", description="", tags=["population"])

    def render(self):
        covering = [(self.malaria, FULL), (self.pop, FULL)]
        return boundary_page(self.page, covering, {self.adm0.id: 1, self.adm1.id: 7}, "https://app.example")

    def test_structure(self):
        page = self.render()
        self.assertIn("# Nepal boundaries\n", page)
        self.assertIn("## ADM1 (Provinces) {#adm1}", page)
        self.assertIn("### geoBoundaries v6 - Nepal ADM1 (Provinces) {#gb-57dcd43-npl-adm1}", page)
        self.assertIn("| Features | 7 |", page)
        self.assertIn("| geoBoundaries version | 57dcd43 |", page)
        self.assertIn("[GeoQuery](https://app.example)", page)
        self.assertIn("## Datasets for Nepal {#datasets}", page)
        self.assertIn("| [Malaria Incidence](../datasets/malaria.md) | — | Full |", page)
        self.assertEqual(page.count("## Citation"), 1)

    def test_description_names_topics(self):
        description = self.render().split("\n")[1]
        self.assertIn("Nepal administrative boundaries (ADM0 to ADM1).", description)
        self.assertIn("Free to extract with GeoQuery: 2 datasets, including population and malaria.", description)

    def realistic_covering(self):
        """63 datasets carrying every topic tag, as in production."""
        tags = ["population", "nighttimelights", "malaria", "conflict", "precipitation", "temperature"]
        covering = [(make_dataset(f"ds{i}", tags=[tag]), FULL) for i, tag in enumerate(tags)]
        covering += [(make_dataset(f"other{i}", tags=["other"]), FULL) for i in range(57)]
        return covering

    def test_realistic_description_keeps_the_dataset_sentence(self):
        text = boundary_page(self.page, self.realistic_covering(), {}, "https://app.example")
        description = json.loads(text.split("\n")[1][len("description: "):])
        self.assertLessEqual(len(description), DESCRIPTION_LIMIT)
        self.assertIn("63 datasets, including population, nighttime lights, malaria", description)

    def test_long_country_name_names_fewer_topics_rather_than_none(self):
        congo = make_fc("gB_57dcd43_COD_ADM0", 0, group_name="gb_v6_cod",
                        group_title="Democratic Republic of the Congo - GeoBoundaries v6")
        page = build_pages([congo])[0]
        text = boundary_page(page, self.realistic_covering(), {}, "https://app.example")
        description = json.loads(text.split("\n")[1][len("description: "):])
        self.assertLessEqual(len(description), DESCRIPTION_LIMIT)
        self.assertIn("Democratic Republic of the Congo administrative boundaries", description)
        self.assertIn("63 datasets, including population", description)


class TopicsTests(TestCase):
    def test_order_and_limit(self):
        datasets = [Dataset(tags=["malaria", "conflict"]), Dataset(tags=["population", "landcover"]),
                    Dataset(tags=["nighttimelights"])]
        self.assertEqual(topics(datasets), ["population", "nighttime lights", "malaria", "conflict"])


class IndexTests(TestCase):
    def test_datasets_index_links_every_dataset(self):
        index = datasets_index([make_dataset()])
        self.assertIn("| [Malaria Incidence](malaria.md) | raster |", index)

    def test_boundaries_index_lists_countries(self):
        pages = build_pages([make_fc("gB_57dcd43_NPL_ADM0", 0), make_fc("gB_57dcd43_NPL_ADM2", 2)])
        self.assertIn("| [Nepal](gb-npl.md) | ADM0–ADM2 |", boundaries_index(pages))


class RedirectTests(TestCase):
    def test_redirect_stub(self):
        stub = redirect_html("../gb-npl/#gb-57dcd43-npl-adm1")
        self.assertIn('<meta name="robots" content="noindex">', stub)
        self.assertIn('content="0; url=../gb-npl/#gb-57dcd43-npl-adm1"', stub)
        self.assertNotIn("canonical", stub)
        self.assertIn('<a href="../gb-npl/#gb-57dcd43-npl-adm1">', stub)


def make_atlas(name, title, description, day, level=None):
    fc = FeatureCollection.objects.create(
        name=name, path=f"/{name}", group_name="atlasofurbanexpansion2016", group_level=level,
        group_title="Atlas of Urban Expansion", source_name="Atlas", title=title,
        description=description, active=True, public=True,
    )
    added = datetime(2026, 8, day, tzinfo=timezone.utc)
    FeatureCollection.objects.filter(id=fc.id).update(date_added=added)
    fc.date_added = added
    return fc


class NonGeoboundariesPageTests(TestCase):
    def test_multi_collection_shows_each_description_and_intro_once(self):
        a = make_atlas("atlas_a", "Atlas A", "Older description.", 10)
        b = make_atlas("atlas_b", "Atlas B", "Newest description.", 12)
        page = build_pages([a, b])[0]
        text = boundary_page(page, [], {}, "https://app.example")
        self.assertIn("# Atlas of Urban Expansion\n", text)
        self.assertIn("## Atlas A {#atlas-a}", text)
        self.assertIn("## Atlas B {#atlas-b}", text)
        self.assertEqual(text.count("Newest description."), 2)  # intro + its own block
        self.assertEqual(text.count("Older description."), 1)
        self.assertIn("No datasets in GeoQuery cover these boundaries yet.", text)

    def test_single_collection_description_once(self):
        a = make_atlas("atlas_a", "Atlas A", "Only description.", 10)
        text = boundary_page(build_pages([a])[0], [], {}, "https://app.example")
        self.assertEqual(text.count("Only description."), 1)

    def test_level_heading_and_index(self):
        a = make_atlas("atlas_a", "Atlas A", "d", 10, level=2)
        pages = build_pages([a])
        text = boundary_page(pages[0], [], {}, "https://app.example")
        self.assertIn("## Level 2 {#level-2}", text)
        self.assertIn("### Atlas A {#atlas-a}", text)
        index = boundaries_index(pages)
        self.assertIn("## Other boundary sets", index)
        self.assertIn("plus 1 other boundary set.", index)
        self.assertNotIn("1 other boundary sets", index)
        self.assertIn("| [Atlas of Urban Expansion](atlasofurbanexpansion2016.md) | 1 | Atlas |", index)


class MarkdownSafetyTests(TestCase):
    def test_pipes_and_newlines_stay_in_one_row(self):
        ds = make_dataset(title="A|B", is_global=True)
        DatasetResource.objects.create(dataset=ds, name="r", path="/x", label="a|b\nc")
        page = dataset_page(ds, [])
        self.assertIn("# A|B\n", page)  # headings are not tables
        self.assertIn("| r | a\\|b c | — |", page)
        index = datasets_index([ds])
        self.assertIn("| [A\\|B](malaria.md) |", index)

    def test_brackets_in_link_labels_escaped(self):
        ds = make_dataset(title="Pop [v2]")
        text = datasets_index([ds])
        self.assertIn("[Pop \\[v2\\]](malaria.md)", text)

    def test_heading_text_cannot_split_anchor(self):
        ds = make_dataset(title="Pop {#x}\nmore")
        self.assertIn("# Pop #x more\n", dataset_page(ds, []))

    def test_details_are_prose(self):
        ds = make_dataset(details="# Heading\nline two\n\n\n| a | b |")
        page = dataset_page(ds, [])
        self.assertIn("\\# Heading line two\n\n| a | b |", page)


class CoverageAndEmptyStateTests(TestCase):
    def setUp(self):
        self.adm0 = make_fc("gB_57dcd43_NPL_ADM0", 0)
        self.page = build_pages([self.adm0])[0]

    def test_partial_on_boundary_page(self):
        ds = make_dataset(tags=[])
        text = boundary_page(self.page, [(ds, PARTIAL)], {}, "https://app.example")
        self.assertIn("| [Malaria Incidence](../datasets/malaria.md) | — | Partial |", text)
        self.assertIn("Free to extract with GeoQuery: 1 dataset.", text.split("\n")[1])

    def test_no_covering_datasets(self):
        text = boundary_page(self.page, [], {}, "https://app.example")
        self.assertIn("No datasets in GeoQuery cover these boundaries yet.", text)

    def test_regional_dataset_without_pages(self):
        text = dataset_page(make_dataset(is_global=False), [])
        self.assertIn("No boundaries in GeoQuery are within this dataset's coverage yet.", text)

    def test_single_level_lead(self):
        text = boundary_page(self.page, [], {}, "https://app.example")
        self.assertIn("Nepal administrative boundaries (ADM0).", text.split("\n")[1])

    def test_level_range_lead(self):
        page = build_pages([self.adm0, make_fc("gB_57dcd43_NPL_ADM3", 3)])[0]
        text = boundary_page(page, [], {}, "https://app.example")
        self.assertIn("Nepal administrative boundaries (ADM0 to ADM3).", text.split("\n")[1])

    def test_anchor_matches_redirect_target(self):
        text = boundary_page(self.page, [], {self.adm0.id: 1}, "https://app.example")
        self.assertIn(f"{{#{slug(self.adm0.name)}}}", text)


class DetailRowTests(TestCase):
    def test_license_link_and_factor(self):
        ds = make_dataset(license="CC BY 4.0", license_url="https://cc.example/by", variable_description="Rate",
                          variable_factor=0.01)
        page = dataset_page(ds, [])
        self.assertIn("| License | [CC BY 4.0](https://cc.example/by) |", page)
        self.assertIn("| Variable | Rate (factor: 0.01) |", page)

    def test_source_url_without_name(self):
        ds = make_dataset(source_url="https://src.example")
        self.assertIn("| Source | [https://src.example](https://src.example) |", dataset_page(ds, []))

    def test_index_license_not_recorded(self):
        self.assertIn("| Not recorded |", datasets_index([make_dataset()]))
