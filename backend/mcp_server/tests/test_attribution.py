"""Attribution builder: full metadata, missing metadata, and request payloads."""

from django.test import TestCase

from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from geoquery.citations import doi_from_citation
from mcp_server.data.attribution import (
    attribution_for,
    attribution_for_request,
    attribution_text,
    missing_attribution,
)


def make_dataset(**kwargs):
    kwargs.setdefault("path", f"/data/rasters/{kwargs['name']}")
    kwargs.setdefault("type", "raster")
    return Dataset.objects.create(**kwargs)


def make_fc(**kwargs):
    kwargs.setdefault("path", f"/data/boundaries/{kwargs['name']}.gpkg")
    return FeatureCollection.objects.create(**kwargs)


class DoiExtractionTests(TestCase):
    def test_bare_doi(self):
        self.assertEqual(
            doi_from_citation("Smith (2019). 10.1016/j.cageo.2018.10.009"),
            "10.1016/j.cageo.2018.10.009",
        )

    def test_resolver_url_yields_the_identifier_not_the_url(self):
        self.assertEqual(
            doi_from_citation("Goodman et al. https://doi.org/10.1016/j.cageo.2018.10.009"),
            "10.1016/j.cageo.2018.10.009",
        )

    def test_trailing_sentence_punctuation_is_not_part_of_the_doi(self):
        self.assertEqual(
            doi_from_citation("See doi:10.5281/zenodo.12345."), "10.5281/zenodo.12345"
        )

    def test_no_doi(self):
        self.assertIsNone(doi_from_citation("A dataset with no identifier"))
        self.assertIsNone(doi_from_citation(None))


class AttributionForTests(TestCase):
    def setUp(self):
        self.complete = make_dataset(
            name="esa_landcover",
            title="ESA Land Cover",
            source_name="ESA CCI",
            source_url="https://climate.esa.int/",
            license="ESA CCI Data Policy",
            license_url="https://climate.esa.int/en/data/access/",
            citation="Defourny, P. (2017). Land Cover Maps v2.0.7. 10.5285/abc",
        )
        self.fc = make_fc(
            name="gB_v6_GHA_ADM2",
            title="Ghana ADM2",
            source_name="geoBoundaries",
            source_url="https://www.geoboundaries.org/",
            license="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            citation="Runfola et al. (2020). geoBoundaries. PLoS ONE.",
        )

    def test_full_metadata_round_trip(self):
        attr = attribution_for([self.complete], [self.fc])

        (ds,) = attr["datasets"]
        self.assertEqual(ds["title"], "ESA Land Cover")
        self.assertEqual(ds["license"], "ESA CCI Data Policy")
        self.assertEqual(ds["doi"], "10.5285/abc")
        self.assertIsNone(ds["notes"])

        (fc,) = attr["boundaries"]
        self.assertEqual(fc["license"], "CC BY 4.0")
        self.assertIsNone(fc["notes"])

        self.assertEqual(attr["geoquery"]["doi"], "10.1016/j.cageo.2018.10.009")

    def test_compact_text_names_data_boundaries_and_geoquery(self):
        text = attribution_for([self.complete], [self.fc])["text"]

        self.assertEqual(
            text,
            "Data: ESA Land Cover (ESA CCI Data Policy) · "
            "Boundaries: geoBoundaries (CC BY 4.0) · Accessed via GeoQuery",
        )

    def test_boundaries_from_one_source_collapse_to_one_entry(self):
        make_fc(
            name="gB_v6_GHA_ADM1",
            title="Ghana ADM1",
            source_name="geoBoundaries",
            license="CC BY 4.0",
        )
        fcs = FeatureCollection.objects.order_by("name")

        text = attribution_for([], fcs)["text"]

        self.assertEqual(
            text, "Boundaries: geoBoundaries (CC BY 4.0) · Accessed via GeoQuery"
        )

    def test_empty_selection_still_cites_geoquery(self):
        self.assertEqual(attribution_for([], [])["text"], "Accessed via GeoQuery")


class MissingMetadataTests(TestCase):
    """Nothing recorded must be stated, not omitted -- the user is about to
    publish from this and needs to know the obligation is unresolved."""

    def setUp(self):
        self.bare = make_dataset(name="mystery", title="Mystery Data")
        self.sourced = make_dataset(
            name="sourced",
            title="Sourced Data",
            source_name="Some Agency",
            source_url="https://example.org/data",
        )

    def test_keys_are_present_and_null_rather_than_absent(self):
        (item,) = attribution_for([self.bare])["datasets"]

        for key in ("license", "license_url", "citation", "doi", "source_name"):
            self.assertIn(key, item)
            self.assertIsNone(item[key])

    def test_notes_name_both_gaps(self):
        (item,) = attribution_for([self.bare])["datasets"]

        self.assertIn("citation not recorded", item["notes"])
        self.assertIn("license not recorded", item["notes"])

    def test_text_falls_back_to_source_name_and_url(self):
        text = attribution_for([self.sourced])["text"]

        self.assertIn("license not recorded", text)
        self.assertIn("Some Agency", text)
        self.assertIn("https://example.org/data", text)

    def test_missing_attribution_lists_the_gaps(self):
        attr = attribution_for([self.bare, self.sourced])

        self.assertEqual(
            missing_attribution(attr),
            {
                "missing_citation": ["Mystery Data", "Sourced Data"],
                "missing_license": ["Mystery Data", "Sourced Data"],
            },
        )


class AttributionTextTests(TestCase):
    def setUp(self):
        self.ds = make_dataset(
            name="ds",
            title="A Dataset",
            license="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            citation="Author, A. (2020). A Dataset. Journal.",
        )
        self.bare = make_dataset(
            name="bare", title="Bare", source_name="Agency", source_url="https://x.test"
        )

    def test_geoquery_leads_the_numbered_reference_list(self):
        text = attribution_text(attribution_for([self.ds]))

        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("1. Goodman, S., BenYishay, A."))
        self.assertEqual(lines[1], "2. Author, A. (2020). A Dataset. Journal.")
        self.assertEqual(
            lines[2],
            "   License: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
        )

    def test_recorded_citation_is_passed_through_verbatim(self):
        text = attribution_text(attribution_for([self.ds]), style="plain")

        self.assertIn("Author, A. (2020). A Dataset. Journal.", text)
        self.assertNotIn("2. Author", text)

    def test_uncited_item_is_flagged_inline(self):
        text = attribution_text(attribution_for([self.bare]))

        self.assertIn("Bare. Agency. https://x.test [citation not recorded", text)


class AttributionForRequestTests(TestCase):
    def setUp(self):
        self.dataset = make_dataset(
            name="ds", title="A Dataset", license="CC BY 4.0", citation="Author (2020)."
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset, short_name="mean", function="f", active=True, public=True
        )
        self.fc = make_fc(
            name="fc", title="A Boundary", source_name="geoBoundaries", license="CC BY 4.0"
        )
        self.fm = FeatMap.objects.create(
            fc=self.fc, geom=Feature.objects.create(shape="POINT(0 0)")
        )
        self.request = Request.objects.create(
            contact="a@example.com",
            status=1,
            data={"datasets": [{"dataset_name": "ds"}]},
        )
        task = ExtractTask.objects.create(
            dataset_id=self.dataset.id,
            resource_ids=[self.resource.id],
            fm=self.fm,
            po=self.po,
        )
        RequestMap.objects.create(
            request=self.request, task=task, dataset_id=self.dataset.id
        )

    def test_boundaries_come_from_the_tasks_the_request_actually_built(self):
        attr = attribution_for_request(self.request)

        self.assertEqual([d["name"] for d in attr["datasets"]], ["ds"])
        self.assertEqual([b["name"] for b in attr["boundaries"]], ["fc"])

    def test_dataset_name_with_no_surviving_row_is_skipped(self):
        self.request.data = {
            "datasets": [{"dataset_name": "ds"}, {"dataset_name": "deleted"}]
        }

        attr = attribution_for_request(self.request)

        self.assertEqual([d["name"] for d in attr["datasets"]], ["ds"])
