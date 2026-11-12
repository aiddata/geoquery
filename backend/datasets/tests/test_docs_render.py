from datetime import datetime, timezone

from django.test import TestCase

from datasets.docs.coverage import FULL, PARTIAL
from datasets.docs.grouping import build_pages
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
    fc = FeatureCollection.objects.create(
        name=name, path=f"/{name}", group_name="gb_v6_npl", group_level=level,
        group_title="Nepal - GeoBoundaries v6", source_name="geoBoundaries",
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
        self.assertIn("Nepal administrative boundaries from geoBoundaries, ADM0 to ADM1.", description)
        self.assertIn("including population and malaria", description)


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
        self.assertIn('<link rel="canonical" href="../gb-npl/#gb-57dcd43-npl-adm1">', stub)
