"""DocBuilder: the results-zip documentation page.

The licence rows and the boundaries block are what a reader of a downloaded
zip has to work from months later, offline, with no access to the app -- so
they are asserted on the rendered HTML rather than on the builder's internals.
"""

import tempfile
from pathlib import Path

from django.test import TestCase

from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from analytics.tasks.documentation import DocBuilder
from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection


class DocBuilderAttributionTests(TestCase):
    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="ds",
            path="/data/rasters/ds",
            type="raster",
            title="A Dataset",
            source_name="Some Agency",
            source_url="https://agency.test",
            license="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            citation="Author, A. (2020). A Dataset.",
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset,
            short_name="mean",
            function="f",
            active=True,
            public=True,
        )
        self.fc = FeatureCollection.objects.create(
            name="gB_v6_GHA_ADM2",
            path="/data/boundaries/gha2.gpkg",
            title="Ghana ADM2",
            source_name="geoBoundaries",
            source_url="https://www.geoboundaries.org/",
            license="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            citation="Runfola, D. et al. (2020). geoBoundaries.",
        )
        self.fm = FeatMap.objects.create(
            fc=self.fc, geom=Feature.objects.create(shape="POINT(0 0)")
        )
        self.request = Request.objects.create(
            contact="a@example.com",
            custom_name="My export",
            status=1,
            data={"datasets": [{"dataset_name": "ds", "dataset_type": "raster"}]},
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

    def render(self) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "doc.html"
            DocBuilder(self.request, out, "http://localhost:8000").build_doc()
            return out.read_text(encoding="utf-8")

    def test_dataset_card_carries_a_license_row(self):
        html = self.render()

        self.assertIn("<th>License</th>", html)
        self.assertIn(
            '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>', html
        )

    def test_boundaries_block_names_source_license_and_citation(self):
        html = self.render()

        self.assertIn("Boundaries (1)", html)
        self.assertIn("Ghana ADM2", html)
        self.assertIn('<a href="https://www.geoboundaries.org/">geoBoundaries</a>', html)
        self.assertIn("Runfola, D. et al. (2020). geoBoundaries.", html)

    def test_unrecorded_license_says_so_instead_of_rendering_blank(self):
        Dataset.objects.filter(pk=self.dataset.pk).update(license=None, license_url=None)
        FeatureCollection.objects.filter(pk=self.fc.pk).update(license=None)

        html = self.render()

        self.assertEqual(
            html.count("Not recorded — check the source before redistributing"), 2
        )

    def test_unrecorded_boundary_citation_says_so(self):
        FeatureCollection.objects.filter(pk=self.fc.pk).update(citation=None)

        self.assertIn("Not recorded — cite the source above", self.render())

    def test_geoquery_citation_still_rendered(self):
        self.assertIn("GeoQuery: Integrating HPC systems", self.render())

    def test_request_with_no_tasks_omits_the_boundaries_block(self):
        RequestMap.objects.all().delete()

        self.assertNotIn("Boundaries (", self.render())
